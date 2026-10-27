"""Bounded project ownership transfer between personal workspaces.

The source project's immutable history cannot be re-parented because finalized versions and
assets are database-guarded. A transfer copies the immutable version graph and content assets
into the recipient's personal workspace, then soft-deletes the source project in the same
database transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import Project, User, Workspace, WorkspaceKind, WorkspaceRole
from app.models.execution import ACTIVE_JOB_STATUSES, Job, MeshModifier, Operation
from app.models.marketplace import ListingStatus, MarketplaceItem
from app.models.plan_annotations import PlanAnnotations
from app.models.references import ProjectReference
from app.models.versioning import (
    Asset,
    ModelComment,
    ModelCommentAsset,
    ProjectVersion,
    VersionComment,
    VersionState,
)
from app.services import projects, signin
from app.services.asset_copies import copy_asset_to_workspace
from app.services.authz import require_workspace_role
from app.storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class TransferResult:
    source_project_id: uuid.UUID
    target_project_id: uuid.UUID
    recipient_email: str
    version_count: int
    asset_count: int
    transferred_at: datetime


def _replace_ids(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_ids(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ids(item, replacements) for item in value]
    if isinstance(value, tuple):
        return [_replace_ids(item, replacements) for item in value]
    if isinstance(value, uuid.UUID):
        replacement = replacements.get(str(value))
        return uuid.UUID(replacement) if replacement else value
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def transfer_project(
    db: Session,
    storage: ObjectStorage,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    recipient_email: str,
    confirmation_name: str,
) -> TransferResult:
    source = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, source.workspace_id, WorkspaceRole.owner)
    db.execute(sa.select(Project.id).where(Project.id == source.id).with_for_update())
    db.refresh(source)
    if source.deleted_at is not None:
        raise NotFoundError("project", source.id)
    if confirmation_name != source.name:
        raise ValidationFailedError(
            "type the exact project name to confirm the transfer",
            {"field": "confirmation_name"},
        )

    normalized_email = signin.normalize_email(recipient_email)
    recipient = db.scalar(sa.select(User).where(sa.func.lower(User.email) == normalized_email))
    if recipient is None or recipient.id == user_id:
        raise ValidationFailedError("the recipient is unavailable")
    target_workspace = db.scalar(
        sa.select(Workspace)
        .where(
            Workspace.owner_user_id == recipient.id,
            Workspace.kind == WorkspaceKind.personal,
        )
        .order_by(Workspace.created_at, Workspace.id)
        .limit(1)
    )
    if target_workspace is None:
        raise ValidationFailedError("the recipient is unavailable")
    if target_workspace.id == source.workspace_id:
        raise ValidationFailedError("the recipient is already in this workspace")

    active_job = db.scalar(
        sa.select(Job.id).where(
            Job.project_id == source.id,
            Job.status.in_(tuple(ACTIVE_JOB_STATUSES)),
        )
    )
    if active_job is not None:
        raise ConflictError(
            "finish or cancel active project jobs before transferring ownership",
            {"job_id": str(active_job)},
        )

    source_versions = list(
        db.scalars(
            sa.select(ProjectVersion)
            .where(ProjectVersion.project_id == source.id)
            .order_by(ProjectVersion.sequence_no, ProjectVersion.id)
        )
    )
    draft = next(
        (version for version in source_versions if version.state is not VersionState.finalized),
        None,
    )
    if draft is not None:
        raise ConflictError(
            "keep or discard every draft before transferring ownership",
            {"version_id": str(draft.id)},
        )

    active_listing = db.scalar(
        sa.select(MarketplaceItem.id).where(
            MarketplaceItem.project_id == source.id,
            MarketplaceItem.status != ListingStatus.withdrawn.value,
        )
    )
    if active_listing is not None:
        raise ConflictError(
            "withdraw active marketplace listings before transferring ownership",
            {"listing_id": str(active_listing)},
        )

    target = projects.create_project(
        db,
        user_id=recipient.id,
        workspace_id=target_workspace.id,
        name=source.name,
        description=source.description,
    )
    target.license_id = source.license_id
    target.attribution = source.attribution
    target.source_url = source.source_url
    target.remixed_from_project_id = source.remixed_from_project_id
    db.flush()

    version_ids = {version.id: uuid.uuid4() for version in source_versions}
    replacements = {
        str(source.id): str(target.id),
        **{str(old): str(new) for old, new in version_ids.items()},
    }
    copied_assets: dict[uuid.UUID, Asset] = {}

    def copied_asset(asset_id: uuid.UUID) -> Asset:
        existing = copied_assets.get(asset_id)
        if existing is not None:
            return existing
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != source.workspace_id:
            raise ValidationFailedError(
                "project history references an unavailable asset",
                {"asset_id": str(asset_id)},
            )
        copied = copy_asset_to_workspace(
            db,
            storage,
            asset,
            workspace_id=target_workspace.id,
            created_by=recipient.id,
        )
        copied_assets[asset_id] = copied
        replacements[str(asset_id)] = str(copied.id)
        return copied

    for version in source_versions:
        for link in version.assets:
            copied_asset(link.asset_id)

    reference = db.get(ProjectReference, source.id)
    if reference is not None:
        copied_asset(reference.asset_id)

    annotations = list(
        db.scalars(sa.select(PlanAnnotations).where(PlanAnnotations.project_id == source.id))
    )
    for row in annotations:
        for annotation in row.annotations:
            if not isinstance(annotation, dict):
                continue
            photo_ids = annotation.get("photo_asset_ids", [])
            if not isinstance(photo_ids, list):
                raise ValidationFailedError("project annotations contain invalid photo assets")
            for raw_asset_id in photo_ids:
                try:
                    copied_asset(uuid.UUID(str(raw_asset_id)))
                except ValueError as exc:
                    raise ValidationFailedError(
                        "project annotations contain invalid photo assets"
                    ) from exc

    operations_by_version: dict[uuid.UUID, list[Operation]] = {}
    modifiers_by_version: dict[uuid.UUID, list[MeshModifier]] = {}
    comments_by_version = {
        comment.version_id: comment
        for comment in db.scalars(
            sa.select(VersionComment).where(VersionComment.version_id.in_(version_ids))
        )
    }
    model_comments_by_version: dict[uuid.UUID, list[ModelComment]] = {}
    for model_comment in db.scalars(
        sa.select(ModelComment)
        .where(ModelComment.version_id.in_(version_ids))
        .order_by(ModelComment.created_at, ModelComment.id)
    ):
        model_comments_by_version.setdefault(model_comment.version_id, []).append(model_comment)
    model_comment_ids = [
        comment.id for comments in model_comments_by_version.values() for comment in comments
    ]
    model_comment_assets: dict[uuid.UUID, list[ModelCommentAsset]] = {}
    if model_comment_ids:
        for comment_asset_link in db.scalars(
            sa.select(ModelCommentAsset)
            .where(ModelCommentAsset.comment_id.in_(model_comment_ids))
            .order_by(ModelCommentAsset.comment_id, ModelCommentAsset.position)
        ):
            copied_asset(comment_asset_link.asset_id)
            model_comment_assets.setdefault(comment_asset_link.comment_id, []).append(
                comment_asset_link
            )
    for version in source_versions:
        operations = list(
            db.scalars(
                sa.select(Operation)
                .where(Operation.project_version_id == version.id)
                .order_by(Operation.sequence_no)
            )
        )
        modifiers = list(
            db.scalars(
                sa.select(MeshModifier)
                .where(MeshModifier.project_version_id == version.id)
                .order_by(MeshModifier.sequence_no)
            )
        )
        operations_by_version[version.id] = operations
        modifiers_by_version[version.id] = modifiers

    transferred_at = datetime.now(UTC)
    for source_version in source_versions:
        provenance = _replace_ids(source_version.provenance or {}, replacements)
        provenance["ownership_transfer"] = {
            "source_project_id": str(source.id),
            "source_version_id": str(source_version.id),
            "recipient_user_id": str(recipient.id),
            "transferred_at": transferred_at.isoformat(),
        }
        target_version = ProjectVersion(
            id=version_ids[source_version.id],
            project_id=target.id,
            parent_version_id=(
                version_ids[source_version.parent_version_id]
                if source_version.parent_version_id is not None
                else None
            ),
            sequence_no=source_version.sequence_no,
            label=source_version.label,
            provenance=provenance,
            created_by=source_version.created_by,
            created_at=source_version.created_at,
            finalized_at=source_version.finalized_at,
        )
        db.add(target_version)
        db.flush()
        for link in source_version.assets:
            projects.attach_asset(
                db,
                target_version,
                copied_asset(link.asset_id).id,
                link.role,
                workspace_id=target_workspace.id,
                thumbnail_angle=link.thumbnail_angle,
            )
        for operation in operations_by_version[source_version.id]:
            db.add(
                Operation(
                    project_version_id=target_version.id,
                    sequence_no=operation.sequence_no,
                    operation_type=operation.operation_type,
                    schema_version=operation.schema_version,
                    enabled=operation.enabled,
                    params=_replace_ids(operation.params, replacements),
                    entity_refs=_replace_ids(operation.entity_refs, replacements),
                    ai_request_id=None,
                    created_at=operation.created_at,
                )
            )
        for modifier in modifiers_by_version[source_version.id]:
            db.add(
                MeshModifier(
                    project_version_id=target_version.id,
                    sequence_no=modifier.sequence_no,
                    scene_node_id=modifier.scene_node_id,
                    modifier_key=modifier.modifier_key,
                    modifier_type=modifier.modifier_type,
                    enabled=modifier.enabled,
                    tolerance_mm=modifier.tolerance_mm,
                    params=_replace_ids(modifier.params, replacements),
                    created_at=modifier.created_at,
                )
            )
        source_comment = comments_by_version.get(source_version.id)
        if source_comment is not None:
            db.add(
                VersionComment(
                    version_id=target_version.id,
                    comment=source_comment.comment,
                    revision=source_comment.revision,
                    updated_by=source_comment.updated_by,
                    created_at=source_comment.created_at,
                    updated_at=source_comment.updated_at,
                )
            )
        for model_comment in model_comments_by_version.get(source_version.id, []):
            target_model_comment = ModelComment(
                version_id=target_version.id,
                comment=model_comment.comment,
                point_mm=model_comment.point_mm,
                status=model_comment.status,
                revision=model_comment.revision,
                created_by=model_comment.created_by,
                updated_by=model_comment.updated_by,
                created_at=model_comment.created_at,
                updated_at=model_comment.updated_at,
            )
            db.add(target_model_comment)
            db.flush()
            for comment_asset_link in model_comment_assets.get(model_comment.id, []):
                db.add(
                    ModelCommentAsset(
                        comment_id=target_model_comment.id,
                        asset_id=copied_asset(comment_asset_link.asset_id).id,
                        position=comment_asset_link.position,
                        created_at=comment_asset_link.created_at,
                    )
                )
        projects.finalize_version(db, target_version)

    target.head_version_id = (
        version_ids[source.head_version_id] if source.head_version_id is not None else None
    )
    if reference is not None:
        db.add(
            ProjectReference(
                project_id=target.id,
                asset_id=copied_asset(reference.asset_id).id,
                settings=_replace_ids(reference.settings, replacements),
                updated_at=reference.updated_at,
            )
        )
    for row in annotations:
        db.add(
            PlanAnnotations(
                project_id=target.id,
                plan_id=row.plan_id,
                annotations=_replace_ids(row.annotations, replacements),
                revision=row.revision,
                updated_by=row.updated_by,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    source.deleted_at = transferred_at
    db.flush()
    return TransferResult(
        source_project_id=source.id,
        target_project_id=target.id,
        recipient_email=normalized_email,
        version_count=len(source_versions),
        asset_count=len(copied_assets),
        transferred_at=transferred_at,
    )
