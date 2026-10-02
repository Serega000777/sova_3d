"""Explicit result feedback (self-learning plan, step 2): good / bad / fixed + a short reason.

Anyone who can see the project may rate a result in it — this is a quality signal, not a
project setting, so it does not need the owner-only gate that training consent does.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.models.execution import AIRequest, Job
from app.models.feedback import AIFeedback, FeedbackRating, FeedbackReason
from app.models.versioning import ProjectVersion
from app.services import projects


def create_feedback(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    rating: FeedbackRating,
    reason: FeedbackReason | None,
    ai_request_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
    version_id: uuid.UUID | None,
) -> AIFeedback:
    projects.get_project(db, user_id=user_id, project_id=project_id)

    if ai_request_id is None and job_id is None and version_id is None:
        raise ValidationFailedError(
            "feedback needs at least one of ai_request_id, job_id, version_id"
        )
    if rating == FeedbackRating.bad and reason is None:
        raise ValidationFailedError("a reason is required when rating is 'bad'")
    if rating != FeedbackRating.bad and reason is not None:
        raise ValidationFailedError("a reason is only accepted when rating is 'bad'")

    if ai_request_id is not None:
        request = db.get(AIRequest, ai_request_id)
        if request is None or request.project_id != project_id:
            raise NotFoundError("ai_request", ai_request_id)
    if job_id is not None:
        job = db.get(Job, job_id)
        if job is None or job.project_id != project_id:
            raise NotFoundError("job", job_id)
    if version_id is not None:
        version = db.get(ProjectVersion, version_id)
        if version is None or version.project_id != project_id:
            raise NotFoundError("version", version_id)

    record = AIFeedback(
        project_id=project_id,
        ai_request_id=ai_request_id,
        job_id=job_id,
        version_id=version_id,
        user_id=user_id,
        rating=rating,
        reason=reason,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    return record


def list_feedback(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    ai_request_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
) -> list[AIFeedback]:
    projects.get_project(db, user_id=user_id, project_id=project_id)
    query = sa.select(AIFeedback).where(AIFeedback.project_id == project_id)
    if ai_request_id is not None:
        query = query.where(AIFeedback.ai_request_id == ai_request_id)
    if job_id is not None:
        query = query.where(AIFeedback.job_id == job_id)
    if version_id is not None:
        query = query.where(AIFeedback.version_id == version_id)
    query = query.order_by(AIFeedback.created_at.desc())
    return list(db.scalars(query))
