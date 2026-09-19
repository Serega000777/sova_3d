"""Engineering assistant endpoints (T-118, F-005): ask the engineer about a version."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.geometry.region import RegionSelection
from app.services import engineering

router = APIRouter(tags=["engineering"])


class AdviceBody(BaseModel):
    """A question about the part, or nothing — then the engineer reviews the whole part."""

    question: str | None = Field(default=None, max_length=engineering.MAX_QUESTION)
    # What the part is for ("держатель для шланга на улице"): drives the material ranking.
    purpose: str | None = Field(default=None, max_length=500)
    material_id: str | None = Field(default=None, max_length=64)
    # The printer the part is for: its calibration replaces the typical hole undersize.
    printer_profile_id: uuid.UUID | None = None
    # The outlined area the question is about, as the region editor produces it.
    region: RegionSelection | None = None


class EngineeringReportOut(BaseModel):
    id: uuid.UUID
    project_version_id: uuid.UUID
    material_id: str | None
    question: str | None
    region: dict[str, Any] | None
    report: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/models/{version_id}/engineering",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def ask_the_engineer(
    version_id: uuid.UUID,
    body: AdviceBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = engineering.enqueue_advice(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        question=body.question,
        purpose=body.purpose,
        material_id=body.material_id,
        printer_profile_id=body.printer_profile_id,
        region=body.region.model_dump(mode="json") if body.region else None,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/models/{version_id}/engineering", response_model=list[EngineeringReportOut])
def list_engineering_reports(
    version_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[EngineeringReportOut]:
    rows = engineering.list_reports(db, user_id=principal.user_id, version_id=version_id)
    return [EngineeringReportOut.model_validate(row) for row in rows]
