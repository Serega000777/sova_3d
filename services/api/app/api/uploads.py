"""POST /uploads (T-012) and POST /assets/complete (T-013)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, StorageDep
from app.api.errors import NotFoundError, ValidationFailedError, error_response
from app.api.schemas import JobAccepted
from app.models.core import Units, WorkspaceRole
from app.models.versioning import Asset, AssetKind
from app.services import jobs, uploads
from app.services.authz import require_workspace_role

router = APIRouter(tags=["uploads"])


class UploadCreate(BaseModel):
    workspace_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=255, examples=["bracket.stl"])
    content_type: str = Field(min_length=1, max_length=255, examples=["model/stl"])
    byte_size: int = Field(gt=0)


class UploadCreated(BaseModel):
    upload_id: uuid.UUID
    url: str
    method: str = "PUT"
    headers: dict[str, str]
    storage_key: str
    format: str
    max_bytes: int
    expires_at: datetime


class AssetComplete(BaseModel):
    upload_id: uuid.UUID
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    units: Units | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    kind: AssetKind
    sha256: str
    format: str | None
    mime: str
    byte_size: int
    units: Units | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/uploads", status_code=status.HTTP_201_CREATED, response_model=UploadCreated)
def create_upload(
    body: UploadCreate,
    db: DbDep,
    storage: StorageDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> UploadCreated:
    presigned = uploads.create_session(
        db,
        storage,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        filename=body.filename,
        content_type=body.content_type,
        byte_size=body.byte_size,
        idempotency_key=idempotency_key,
    )
    session = presigned.session
    return UploadCreated(
        upload_id=session.id,
        url=presigned.url,
        headers={"Content-Type": session.content_type},
        storage_key=session.storage_key,
        format=session.format_id,
        max_bytes=session.byte_size,
        expires_at=session.expires_at,
    )


@router.post("/assets/complete", status_code=status.HTTP_201_CREATED, response_model=AssetOut)
def complete_asset(
    body: AssetComplete,
    request: Request,
    db: DbDep,
    storage: StorageDep,
    principal: PrincipalDep,
) -> AssetOut | JSONResponse:
    result = uploads.complete(
        db,
        storage,
        user_id=principal.user_id,
        upload_id=body.upload_id,
        sha256=body.sha256,
        units=body.units,
    )
    if isinstance(result, uploads.Rejected):
        return error_response(request, result.error)
    return AssetOut.model_validate(result)


@router.post(
    "/assets/{asset_id}/extract-video-frames",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def extract_video_frames(
    asset_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """Turn a previously uploaded MP4 into four normal JPEG assets in the worker."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError("asset", asset_id)
    require_workspace_role(db, principal.user_id, asset.workspace_id, WorkspaceRole.editor)
    if asset.format != "mp4" or asset.mime != "video/mp4":
        raise ValidationFailedError(
            "frame extraction requires an MP4 video asset",
            {"asset_id": str(asset.id), "format": asset.format, "mime": asset.mime},
        )
    job = jobs.enqueue(
        db,
        workspace_id=asset.workspace_id,
        job_type="extract_video_frames",
        input={"asset_id": str(asset.id)},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
