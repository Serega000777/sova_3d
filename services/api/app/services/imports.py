"""Import and conversion requests (T-110/T-112, F-014/F-015)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, UnsupportedFormatError, ValidationFailedError
from app.formats import FORMATS, Representation, exportable
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import Asset
from app.services import jobs, projects
from app.services.authz import require_workspace_role

IMPORT_JOB = "import_model"
CONVERT_JOB = "convert_asset"

# What the platform can turn a file into. The registry is the single source of truth; the
# worker's exporter must be able to write every one of these (a test keeps them in step).
CONVERTIBLE_SOURCES = frozenset(
    {"stl", "obj", "ply", "glb", "gltf", "3mf", "step", "stp", "iges", "igs"}
)


def _asset_for(db: Session, *, user_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError("asset", asset_id)
    require_workspace_role(db, user_id, asset.workspace_id, WorkspaceRole.editor)
    if asset.format not in CONVERTIBLE_SOURCES:
        raise UnsupportedFormatError(
            "this file is not a model the platform can read",
            {"format": asset.format, "supported": sorted(CONVERTIBLE_SOURCES)},
        )
    return asset


def enqueue_import(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    label: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    """T-110: an uploaded file becomes a version of this project."""
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    asset = _asset_for(db, user_id=user_id, asset_id=asset_id)
    if asset.workspace_id != project.workspace_id:
        raise NotFoundError("asset", asset_id)
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=IMPORT_JOB,
        input={
            "asset_id": str(asset.id),
            "project_id": str(project.id),
            "label": label,
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )


def enqueue_conversion(
    db: Session,
    *,
    user_id: uuid.UUID,
    asset_id: uuid.UUID,
    target_format: str,
    idempotency_key: str | None = None,
) -> Job:
    """T-112: hand back another format, with a report of what the conversion cost."""
    asset = _asset_for(db, user_id=user_id, asset_id=asset_id)
    spec = FORMATS.get(target_format)
    if spec is None or not spec.can_export:
        raise UnsupportedFormatError(
            "that format cannot be written",
            {"format": target_format, "supported": [f.id for f in exportable()]},
        )
    if spec.id == asset.format:
        raise ValidationFailedError("the file is already in that format", {"format": target_format})
    if spec.representation is Representation.brep:
        raise ValidationFailedError(
            "STEP and IGES need a B-Rep, which a mesh file does not have — export them from a "
            "version built from operations or imported as CAD (POST /models/{id}/exports)",
            {"format": target_format},
        )
    return jobs.enqueue(
        db,
        workspace_id=asset.workspace_id,
        job_type=CONVERT_JOB,
        input={"asset_id": str(asset.id), "format": spec.id},
        created_by=user_id,
        idempotency_key=idempotency_key,
    )
