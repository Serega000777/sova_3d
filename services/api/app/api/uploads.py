"""POST /uploads (T-012) and POST /assets/complete (T-013)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, StorageDep
from app.models.core import Units
from app.models.versioning import AssetKind
from app.services import uploads

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
    body: AssetComplete, db: DbDep, storage: StorageDep, principal: PrincipalDep
) -> AssetOut:
    asset = uploads.complete(
        db,
        storage,
        user_id=principal.user_id,
        upload_id=body.upload_id,
        sha256=body.sha256,
        units=body.units,
    )
    return AssetOut.model_validate(asset)
