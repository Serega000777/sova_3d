"""Engineering assistant endpoints (T-118, F-005): ask the engineer about a version."""

import uuid
from datetime import datetime
from typing import Any, Literal

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


class AdaptMaterialBody(BaseModel):
    """F-009: the material the part will be printed in; the plan adapts to it."""

    material_id: str = Field(max_length=64)
    printer_profile_id: uuid.UUID | None = None
    language: str = Field(default="en", pattern="^(en|ru)$")
    # A preview by default: the adapted part is a draft until the user keeps it (T-052).
    preview: bool = True


class AdaptMaterialOut(BaseModel):
    job: JobAccepted
    report: dict[str, Any]


@router.post(
    "/models/{version_id}/adapt-material",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdaptMaterialOut,
)
def adapt_material(
    version_id: uuid.UUID, body: AdaptMaterialBody, db: DbDep, principal: PrincipalDep
) -> AdaptMaterialOut:
    """Walls, floors, holes and corners changed for the material — as an ordinary edit."""
    job, report = engineering.enqueue_material_adaptation(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        material_id=body.material_id,
        printer_profile_id=body.printer_profile_id,
        language=body.language,
        preview=body.preview,
    )
    return AdaptMaterialOut(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type), report=report
    )


class OptimizeBody(BaseModel):
    """F-007: what to optimize for. `lighter` hollows the part to a wall the material carries."""

    goal: Literal["lighter"] = "lighter"
    material_id: str | None = Field(default=None, max_length=64)
    printer_profile_id: uuid.UUID | None = None
    load: Literal["cosmetic", "structural", "load_bearing"] = "structural"
    # where the hollow opens: the face the part prints on, or nowhere (an enclosed void)
    opening: Literal["bottom", "top", "none"] = "bottom"
    wall_mm: float | None = Field(default=None, gt=0.4, le=20.0)
    language: str = Field(default="en", pattern="^(en|ru)$")
    preview: bool = True


@router.post(
    "/models/{version_id}/optimize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdaptMaterialOut,
)
def optimize_model(
    version_id: uuid.UUID, body: OptimizeBody, db: DbDep, principal: PrincipalDep
) -> AdaptMaterialOut:
    """Make the part lighter — a shell to the material's wall, bosses kept around screw holes
    — as an ordinary edit with the mass before in the report and after in the job result."""
    job, report = engineering.enqueue_lightening(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        material_id=body.material_id,
        printer_profile_id=body.printer_profile_id,
        load=body.load,
        opening=body.opening,
        wall_mm=body.wall_mm,
        language=body.language,
        preview=body.preview,
    )
    return AdaptMaterialOut(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type), report=report
    )


@router.get("/models/{version_id}/engineering", response_model=list[EngineeringReportOut])
def list_engineering_reports(
    version_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[EngineeringReportOut]:
    rows = engineering.list_reports(db, user_id=principal.user_id, version_id=version_id)
    return [EngineeringReportOut.model_validate(row) for row in rows]
