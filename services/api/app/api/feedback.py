"""Explicit result feedback endpoints (self-learning plan, step 2): good / bad / fixed."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, model_validator

from app.api.deps import DbDep, PrincipalDep
from app.models.feedback import FeedbackRating, FeedbackReason
from app.services import feedback

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    rating: FeedbackRating
    reason: FeedbackReason | None = None
    ai_request_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_target(self) -> "FeedbackCreate":
        if self.ai_request_id is None and self.job_id is None and self.version_id is None:
            raise ValueError("at least one of ai_request_id, job_id, version_id is required")
        return self


class FeedbackOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    ai_request_id: uuid.UUID | None
    job_id: uuid.UUID | None
    version_id: uuid.UUID | None
    user_id: uuid.UUID | None
    rating: FeedbackRating
    reason: FeedbackReason | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/projects/{project_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackOut,
)
def create_feedback(
    project_id: uuid.UUID, body: FeedbackCreate, db: DbDep, principal: PrincipalDep
) -> FeedbackOut:
    record = feedback.create_feedback(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        rating=body.rating,
        reason=body.reason,
        ai_request_id=body.ai_request_id,
        job_id=body.job_id,
        version_id=body.version_id,
    )
    return FeedbackOut.model_validate(record)


@router.get("/projects/{project_id}/feedback", response_model=list[FeedbackOut])
def list_feedback(
    project_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    ai_request_id: Annotated[uuid.UUID | None, Query(description="Filter by AI request")] = None,
    job_id: Annotated[uuid.UUID | None, Query(description="Filter by job")] = None,
    version_id: Annotated[uuid.UUID | None, Query(description="Filter by version")] = None,
) -> list[FeedbackOut]:
    rows = feedback.list_feedback(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        ai_request_id=ai_request_id,
        job_id=job_id,
        version_id=version_id,
    )
    return [FeedbackOut.model_validate(row) for row in rows]
