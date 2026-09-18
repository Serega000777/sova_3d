"""Manual parametric edits (T-055, F-061): typed operations straight to the kernel."""

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import edits

router = APIRouter(tags=["edits"])


class EditCreate(BaseModel):
    """Operations are validated against the same registry the planner is held to."""

    operations: list[dict[str, Any]] = Field(min_length=1, max_length=edits.MAX_EDIT_OPERATIONS)
    label: str | None = Field(default=None, max_length=200)
    # T-052: build it, but leave it a draft the user accepts or rejects.
    preview: bool = False


@router.post(
    "/models/{version_id}/edits",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_edit(
    version_id: uuid.UUID,
    body: EditCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = edits.enqueue_edit(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        operations=body.operations,
        label=body.label,
        preview=body.preview,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
