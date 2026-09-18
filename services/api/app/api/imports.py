"""Bring a model in, take any format out (T-110/T-112, F-014/F-015).

Both work on an asset the user already uploaded through /uploads: importing turns it into a
project version the clients can open, converting just hands back another format with a
report of what the conversion cost.
"""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import imports

router = APIRouter(tags=["imports"])


class ImportBody(BaseModel):
    asset_id: uuid.UUID
    label: str | None = Field(default=None, max_length=200)


class ConvertBody(BaseModel):
    """`format` is one of the exportable ids from GET /formats."""

    format: str = Field(min_length=2, max_length=8)


@router.post(
    "/projects/{project_id}/imports",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def import_model(
    project_id: uuid.UUID,
    body: ImportBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = imports.enqueue_import(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        asset_id=body.asset_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/assets/{asset_id}/convert",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def convert_asset(
    asset_id: uuid.UUID,
    body: ConvertBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = imports.enqueue_conversion(
        db,
        user_id=principal.user_id,
        asset_id=asset_id,
        target_format=body.format,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
