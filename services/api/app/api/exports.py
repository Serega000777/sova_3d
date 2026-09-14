"""Exports (F-014/F-076): POST /models/{version_id}/exports, GET /assets/{id}/download."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, StorageDep
from app.api.errors import NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.models.versioning import Asset
from app.services import jobs, projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.authz import require_workspace_role

router = APIRouter(tags=["exports"])
EXPORT_FORMATS = ("stl", "glb", "3mf")


class ExportCreate(BaseModel):
    format: Literal["stl", "glb", "3mf"]
    printable: bool = False


class DownloadOut(BaseModel):
    asset_id: uuid.UUID
    url: str
    format: str | None
    byte_size: int
    expires_in_seconds: int
    created_at: datetime


@router.post(
    "/models/{version_id}/exports",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_export(
    version_id: uuid.UUID,
    body: ExportCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in REPAIRABLE_FORMATS:
        raise ValidationFailedError("version has no mesh asset to export")
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type="export",
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "format": body.format,
            "printable": body.printable,
        },
        created_by=principal.user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/assets/{asset_id}/download", response_model=DownloadOut)
def download_asset(
    asset_id: uuid.UUID, db: DbDep, storage: StorageDep, principal: PrincipalDep
) -> DownloadOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError("asset", asset_id)
    require_workspace_role(db, principal.user_id, asset.workspace_id, WorkspaceRole.viewer)
    ttl = 15 * 60
    return DownloadOut(
        asset_id=asset.id,
        url=storage.presign_get(asset.storage_key, ttl_seconds=ttl),
        format=asset.format,
        byte_size=asset.byte_size,
        expires_in_seconds=ttl,
        created_at=asset.created_at,
    )
