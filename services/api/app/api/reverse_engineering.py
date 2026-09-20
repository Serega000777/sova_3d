"""Reverse engineering endpoints (T-160, F-024/F-011)."""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import reverse_engineering

router = APIRouter(tags=["reverse-engineering"])


class ReconstructionBody(BaseModel):
    tolerance_mm: float = Field(default=0.2, gt=0.01, le=5.0)
    max_levels: int = Field(default=64, ge=8, le=200)
    samples: int = Field(default=3000, ge=200, le=20000)
    threads: bool = True


@router.post(
    "/models/{version_id}/reconstruct",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def reconstruct_model(
    version_id: uuid.UUID,
    body: ReconstructionBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = reverse_engineering.enqueue_reconstruction(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        tolerance_mm=body.tolerance_mm,
        max_levels=body.max_levels,
        samples=body.samples,
        threads=body.threads,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
