"""Project CRUD (T-014) and immutable project versions (T-015).

Versions are append-only: every edit creates a new ProjectVersion whose
parent_version_id points at what it was derived from. The database
triggers from migration 0002 make finalized versions immutable; this module
is the only place that should create or finalize them.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import Project, WorkspaceRole
from app.models.versioning import (
    CONTENT_ROLES,
    Asset,
    AssetRole,
    ProjectVersion,
    VersionAsset,
    VersionState,
)
from app.services.authz import require_workspace_role

# --- projects ------------------------------------------------------------------------------


def create_project(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    name: str,
    description: str | None = None,
) -> Project:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    project = Project(workspace_id=workspace_id, name=name, description=description)
    db.add(project)
    db.flush()
    return project


def get_project(db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    """Load a project the user may see. Unknown, deleted or foreign projects are all 404."""
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise NotFoundError("project", project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.viewer)
    return project


def list_projects(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[Project]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return list(
        db.scalars(
            sa.select(Project)
            .where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc(), Project.id)
            .limit(limit)
            .offset(offset)
        )
    )


def update_project(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    project = get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    db.flush()
    return project


def delete_project(db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Soft delete: versions and assets stay for lineage/retention policy."""
    project = get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.admin)
    project.deleted_at = datetime.now(UTC)
    db.flush()


# --- versions ------------------------------------------------------------------------------


def get_version(db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID) -> ProjectVersion:
    version = db.get(ProjectVersion, version_id)
    if version is None:
        raise NotFoundError("project_version", version_id)
    get_project(db, user_id=user_id, project_id=version.project_id)
    return version


def list_versions(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[ProjectVersion]:
    get_project(db, user_id=user_id, project_id=project_id)
    return list(
        db.scalars(
            sa.select(ProjectVersion)
            .where(ProjectVersion.project_id == project_id)
            .order_by(ProjectVersion.sequence_no.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def create_version(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    parent_version_id: uuid.UUID | None = None,
    label: str | None = None,
    provenance: dict[str, Any] | None = None,
    assets: dict[AssetRole, uuid.UUID] | None = None,
    finalize: bool = True,
) -> ProjectVersion:
    """Append a version on behalf of a user (editor role required)."""
    project = get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    return create_version_internal(
        db,
        project_id=project_id,
        parent_version_id=parent_version_id,
        label=label,
        provenance=provenance,
        assets=assets,
        finalize=finalize,
        created_by=user_id,
    )


def create_version_internal(
    db: Session,
    *,
    project_id: uuid.UUID,
    parent_version_id: uuid.UUID | None = None,
    label: str | None = None,
    provenance: dict[str, Any] | None = None,
    assets: dict[AssetRole, uuid.UUID] | None = None,
    finalize: bool = True,
    created_by: uuid.UUID | None = None,
) -> ProjectVersion:
    """Append a version without an authorization check — for job handlers whose request
    was authorized at enqueue time. `parent_version_id` defaults to the project's head;
    passing an older ancestor creates a branch. Assets are attached by role and must belong
    to the same workspace. Finalizing (the default) freezes content roles immediately."""
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise NotFoundError("project", project_id)

    parent_id = parent_version_id if parent_version_id is not None else project.head_version_id
    if parent_id is not None:
        parent = db.get(ProjectVersion, parent_id)
        if parent is None or parent.project_id != project_id:
            raise NotFoundError("parent_version", parent_id)
        if parent.state is not VersionState.finalized:
            raise ConflictError("parent version is still a draft", {"parent_id": str(parent_id)})

    # Atomic: a failed asset attachment must not leave a half-built version behind.
    with db.begin_nested():
        # Row lock on the project serialises sequence_no allocation for concurrent editors.
        db.execute(sa.select(Project.id).where(Project.id == project_id).with_for_update())
        next_seq = (
            db.scalar(
                sa.select(sa.func.coalesce(sa.func.max(ProjectVersion.sequence_no), 0)).where(
                    ProjectVersion.project_id == project_id
                )
            )
            or 0
        ) + 1

        version = ProjectVersion(
            project_id=project_id,
            parent_version_id=parent_id,
            sequence_no=next_seq,
            label=label,
            provenance={
                **(provenance or {}),
                "parent_version_id": str(parent_id) if parent_id else None,
            },
            created_by=created_by,
        )
        db.add(version)
        db.flush()

        for role, asset_id in (assets or {}).items():
            attach_asset(db, version, asset_id, role, workspace_id=project.workspace_id)

        if finalize:
            finalize_version(db, version)
    return version


def attach_asset(
    db: Session,
    version: ProjectVersion,
    asset_id: uuid.UUID,
    role: AssetRole,
    *,
    workspace_id: uuid.UUID,
) -> VersionAsset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise NotFoundError("asset", asset_id)
    if version.state is VersionState.finalized and role in CONTENT_ROLES:
        raise ConflictError(
            "content assets of a finalized version are frozen", {"role": role.value}
        )
    link = VersionAsset(version_id=version.id, asset_id=asset_id, role=role)
    db.add(link)
    db.flush()
    return link


def finalize_version(db: Session, version: ProjectVersion) -> ProjectVersion:
    """Freeze the version and advance the project head when it extends the current head."""
    if version.state is VersionState.finalized:
        return version
    version.state = VersionState.finalized
    db.flush()
    project = db.get(Project, version.project_id)
    if project is not None and project.head_version_id in (None, version.parent_version_id):
        project.head_version_id = version.id
        db.flush()
    db.refresh(version)
    return version


def finalize_version_as(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID
) -> ProjectVersion:
    version = get_version(db, user_id=user_id, version_id=version_id)
    project = get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    return finalize_version(db, version)


def lineage(db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID) -> list[ProjectVersion]:
    """Ancestors from the given version back to the root, newest first."""
    chain: list[ProjectVersion] = []
    current: ProjectVersion | None = get_version(db, user_id=user_id, version_id=version_id)
    while current is not None:
        chain.append(current)
        current = (
            db.get(ProjectVersion, current.parent_version_id)
            if current.parent_version_id is not None
            else None
        )
    return chain


def discard_version(db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """T-052 reject: throw away a preview. Only a draft can go; history never can."""
    version = get_version(db, user_id=user_id, version_id=version_id)
    project = get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if version.state is VersionState.finalized:
        raise ConflictError(
            "a finalized version is part of the project's history and cannot be discarded",
            {"version_id": str(version.id)},
        )
    if project.head_version_id == version.id:  # never orphan the project's head
        project.head_version_id = version.parent_version_id
        db.flush()
    # The database cascades these; tell the ORM so it does not try to null them out first.
    db.execute(sa.delete(VersionAsset).where(VersionAsset.version_id == version.id))
    db.expire(version, ["assets"])
    db.delete(version)
    db.flush()


def _measurements(version: ProjectVersion) -> dict[str, Any]:
    """What a user compares: size, volume, and how the model was built."""
    provenance = version.provenance or {}
    bodies = provenance.get("bodies") or []
    body = bodies[-1] if isinstance(bodies, list) and bodies else {}
    bbox = body.get("bbox_mm") or {}
    operations = provenance.get("plan_goal")
    return {
        "version_id": str(version.id),
        "sequence_no": version.sequence_no,
        "label": version.label,
        "state": version.state.value,
        "size_mm": bbox.get("size"),
        "volume_mm3": body.get("volume_mm3"),
        "surface_area_mm2": body.get("surface_area_mm2"),
        "valid": body.get("valid"),
        "body": body.get("name"),
        "operation": provenance.get("operation"),
        "goal": operations,
    }


def compare_versions(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID, against_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Before/after for a preview (T-052): the two states and what changed between them.

    With no `against`, the comparison is to the version this one was built from — which is
    what a preview is: this change, against what the user had.
    """
    after = get_version(db, user_id=user_id, version_id=version_id)
    before_id = against_id if against_id is not None else after.parent_version_id
    before = (
        get_version(db, user_id=user_id, version_id=before_id) if before_id is not None else None
    )
    if before is not None and before.project_id != after.project_id:
        raise ValidationFailedError("the two versions belong to different projects")

    before_state = _measurements(before) if before is not None else None
    after_state = _measurements(after)
    changed: dict[str, Any] = {}
    if before_state is not None:
        for key in ("size_mm", "volume_mm3", "surface_area_mm2", "valid"):
            if before_state.get(key) != after_state.get(key):
                changed[key] = {"before": before_state.get(key), "after": after_state.get(key)}
        if before_state.get("volume_mm3") and after_state.get("volume_mm3"):
            delta = float(after_state["volume_mm3"]) - float(before_state["volume_mm3"])
            changed["volume_delta_pct"] = round(delta / float(before_state["volume_mm3"]) * 100, 3)
    operations = (after.provenance or {}).get("edit_operations") or []
    return {
        "before": before_state,
        "after": after_state,
        "changed": changed,
        "edit_operations": operations,
        "awaiting_decision": after.state is VersionState.draft,
    }
