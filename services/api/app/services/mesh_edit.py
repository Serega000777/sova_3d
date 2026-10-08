"""Direct mesh editing and surface details (T-235 / T-236, F-086).

The API side checks that the version can be edited as a mesh and enqueues; the worker does the
editing. A parametric version — one built from operations or imported as CAD — keeps its exact
B-Rep unless the caller explicitly asks to convert it to a mesh, so a click never silently
degrades a model the kernel can still change exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.geometry import mesh_edit as mesh_schema
from app.models.core import WorkspaceRole
from app.models.execution import Job, MeshModifier, Operation
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.services import jobs, projects, scenes
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

MESH_EDIT_JOB = "mesh_edit"
EDITABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})


@dataclass(frozen=True)
class StackModifier:
    key: str
    operation: dict[str, Any]
    enabled: bool
    tolerance_mm: float


def modifier_stacks(db: Session, version_id: uuid.UUID) -> dict[str | None, list[StackModifier]]:
    """Return every node-scoped stack in one immutable version."""
    rows = db.scalars(
        sa.select(MeshModifier)
        .where(MeshModifier.project_version_id == version_id)
        .order_by(MeshModifier.sequence_no)
    ).all()
    result: dict[str | None, list[StackModifier]] = {}
    for row in rows:
        result.setdefault(row.scene_node_id, []).append(
            StackModifier(
                key=row.modifier_key,
                operation=dict(row.params),
                enabled=row.enabled,
                tolerance_mm=row.tolerance_mm,
            )
        )
    return result


def modifier_stack(
    db: Session, version_id: uuid.UUID, *, scene_node_id: str | None = None
) -> list[StackModifier]:
    """Return every stored mesh step, including disabled rows, in display order."""
    node_filter = (
        MeshModifier.scene_node_id.is_(None)
        if scene_node_id is None
        else MeshModifier.scene_node_id == scene_node_id
    )
    rows = db.scalars(
        sa.select(MeshModifier)
        .where(MeshModifier.project_version_id == version_id, node_filter)
        .order_by(MeshModifier.sequence_no)
    ).all()
    return [
        StackModifier(
            key=row.modifier_key,
            operation=dict(row.params),
            enabled=row.enabled,
            tolerance_mm=row.tolerance_mm,
        )
        for row in rows
    ]


def modifier_stack_base(
    db: Session,
    version: ProjectVersion,
    *,
    workspace_id: uuid.UUID,
    scene_node_id: str | None = None,
) -> tuple[uuid.UUID, Asset]:
    """Resolve the immutable mesh a stack replays from and fail closed on stale metadata."""
    provenance = version.provenance or {}
    if scene_node_id is None:
        metadata = provenance.get("mesh_modifier_stack")
    else:
        collections = provenance.get("mesh_modifier_stacks")
        metadata = collections.get(scene_node_id) if isinstance(collections, dict) else None
    if not isinstance(metadata, dict):
        raise ValidationFailedError(
            "this version has no mesh modifier base", {"version_id": str(version.id)}
        )
    try:
        base_version_id = uuid.UUID(str(metadata["base_version_id"]))
        base_asset_id = uuid.UUID(str(metadata["base_asset_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError(
            "the mesh modifier base metadata is invalid", {"version_id": str(version.id)}
        ) from exc
    base_version = db.get(ProjectVersion, base_version_id)
    asset = db.get(Asset, base_asset_id)
    if (
        base_version is None
        or base_version.project_id != version.project_id
        or asset is None
        or asset.workspace_id != workspace_id
        or asset.format not in EDITABLE_FORMATS
        or not any(
            link.role is AssetRole.model and link.asset_id == base_asset_id
            for link in base_version.assets
        )
    ):
        raise ValidationFailedError(
            "the mesh modifier base is unavailable", {"version_id": str(version.id)}
        )
    return base_version_id, asset


def build_modifier_stack(
    db: Session,
    *,
    version: ProjectVersion,
    items: list[dict[str, Any]],
    scene_node_id: str | None = None,
) -> list[StackModifier]:
    """Validate a complete reorder/toggle request without changing the source version."""
    existing = modifier_stack(db, version.id, scene_node_id=scene_node_id)
    if not existing:
        raise ValidationFailedError(
            "this version has no mesh modifier history to edit",
            {"version_id": str(version.id)},
        )
    if len(items) != len(existing):
        raise ValidationFailedError(
            "the mesh modifier stack must include every stored step exactly once",
            {"expected": len(existing), "received": len(items)},
        )
    by_key = {item.key: item for item in existing}
    requested = [str(item.get("id", "")) for item in items]
    if len(set(requested)) != len(requested) or set(requested) != set(by_key):
        raise ValidationFailedError(
            "the mesh modifier stack contains missing, duplicate, or unknown ids",
            {"expected_ids": list(by_key), "received_ids": requested},
        )
    ordered = [
        StackModifier(
            key=key,
            operation=by_key[key].operation,
            enabled=bool(item.get("enabled", True)),
            tolerance_mm=by_key[key].tolerance_mm,
        )
        for key, item in zip(requested, items, strict=True)
    ]
    active = [item for item in ordered if item.enabled]
    if not active:
        raise ValidationFailedError("at least one mesh modifier must remain enabled")
    # Validate every persisted operation again at the API boundary. Geometry-dependent stale
    # selections are checked by the worker while replaying and cannot leave a partial version.
    for item in active:
        validate_request(
            {
                "operations": [item.operation],
                "tolerance_mm": item.tolerance_mm,
            }
        )
    return ordered


def next_modifier_key(stack: list[StackModifier]) -> str:
    used = {item.key for item in stack}
    number = len(stack) + 1
    while f"mesh_{number}" in used:
        number += 1
    return f"mesh_{number}"


def is_parametric(db: Session, version_id: uuid.UUID) -> bool:
    """True when the version carries a kernel operation history (an exact B-Rep)."""
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(Operation)
            .where(Operation.project_version_id == version_id)
        )
        or 0
    ) > 0


def validate_request(request: dict[str, Any]) -> mesh_schema.EditRequest:
    try:
        return mesh_schema.EditRequest.model_validate(request)
    except ValidationError as exc:
        problems = [
            {"where": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()[:8]
        ]
        raise ValidationFailedError("the edit request is not valid", {"errors": problems}) from None


def enqueue_mesh_edit(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    request: dict[str, Any],
    label: str | None = None,
    convert_to_mesh: bool = False,
    scene_node_id: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)

    spec = validate_request(request)
    if scenes.has_explicit_scene(version):
        if scene_node_id is None:
            raise ValidationFailedError("a multi-object scene edit must name scene_node_id")
        target = scenes.editable_object(
            db,
            version=version,
            workspace_id=project.workspace_id,
            node_id=scene_node_id,
        )
        request = scenes.request_in_object_space(
            spec.model_dump(mode="json"), target["world_transform"]
        )
        spec = validate_request(request)
        asset = db.get(Asset, target["resolved_asset_id"])
    else:
        if scene_node_id is not None:
            raise ValidationFailedError(
                "scene_node_id is only valid for an explicit multi-object scene",
                {"scene_node_id": scene_node_id},
            )
        asset = model_asset_of(db, version)
    if asset is None or asset.format not in EDITABLE_FORMATS:
        raise ValidationFailedError(
            "this version has no mesh to edit", {"editable_formats": sorted(EDITABLE_FORMATS)}
        )
    # A preview changes nothing, so it never needs the conversion consent.
    if (
        scene_node_id is None
        and not spec.preview
        and not convert_to_mesh
        and is_parametric(db, version.id)
    ):
        raise ValidationFailedError(
            "this version is parametric; editing its mesh turns it into a plain mesh. "
            "Edit it with operations to keep it exact, or repeat with convert_to_mesh=true",
            {"parametric": True},
        )

    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=MESH_EDIT_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "request": spec.model_dump(mode="json"),
            "label": label,
            "converted_from_parametric": bool(not spec.preview and convert_to_mesh),
            "scene_node_id": scene_node_id,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


def enqueue_modifier_stack_edit(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    items: list[dict[str, Any]],
    label: str | None = None,
    scene_node_id: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if scenes.has_explicit_scene(version):
        if scene_node_id is None:
            raise ValidationFailedError("a multi-object scene stack edit must name scene_node_id")
        scenes.editable_object(
            db,
            version=version,
            workspace_id=project.workspace_id,
            node_id=scene_node_id,
        )
    elif scene_node_id is not None:
        raise ValidationFailedError(
            "scene_node_id is only valid for an explicit multi-object scene",
            {"scene_node_id": scene_node_id},
        )
    ordered = build_modifier_stack(db, version=version, items=items, scene_node_id=scene_node_id)
    modifier_stack_base(
        db,
        version,
        workspace_id=project.workspace_id,
        scene_node_id=scene_node_id,
    )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=MESH_EDIT_JOB,
        input={
            "version_id": str(version.id),
            "modifier_stack": [{"id": item.key, "enabled": item.enabled} for item in ordered],
            "label": label,
            "scene_node_id": scene_node_id,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
