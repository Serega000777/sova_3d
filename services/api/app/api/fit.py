"""AI Fit Test endpoints (T-130, F-027): does part B fit part A?"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import fit

router = APIRouter(tags=["fit"])


class FitTestBody(BaseModel):
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    placement: fit.Placement = Field(default_factory=fit.Placement)
    # The fit the user wants between them; the advice is measured against it.
    wanted: Literal["clearance", "sliding", "transition", "press"] = "sliding"
    material_id: str | None = Field(default=None, max_length=64)
    language: Literal["ru", "en"] = "en"


class FitTestOut(BaseModel):
    id: uuid.UUID
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    placement: dict[str, Any]
    verdict: str
    report: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/fit-tests", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
def start_fit_test(
    body: FitTestBody, db: DbDep, principal: PrincipalDep, idempotency_key: IdempotencyKey = None
) -> JobAccepted:
    job = fit.enqueue_fit_test(
        db,
        user_id=principal.user_id,
        version_a_id=body.version_a_id,
        version_b_id=body.version_b_id,
        placement=body.placement,
        wanted=body.wanted,
        material_id=body.material_id,
        language=body.language,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/models/{version_id}/fit-tests", response_model=list[FitTestOut])
def list_fit_tests(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[FitTestOut]:
    rows = fit.list_fit_tests(db, user_id=principal.user_id, version_id=version_id)
    return [FitTestOut.model_validate(row) for row in rows]
