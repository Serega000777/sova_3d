"""Paint endpoints (T-108, F-034): colour a model without changing its shape."""

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import painting

router = APIRouter(tags=["paint"])

COLOUR = r"^#[0-9a-fA-F]{6}$"


class Stroke(BaseModel):
    """One swipe of colour. Without a region it covers the whole body."""

    colour: str = Field(pattern=COLOUR)
    region: dict[str, Any] | None = None


class PaintBody(BaseModel):
    strokes: list[Stroke] = Field(default_factory=list, max_length=painting.MAX_STROKES)
    base_colour: str | None = Field(default=None, pattern=COLOUR)
    label: str | None = Field(default=None, max_length=200)
    # By default new strokes go on top of the paint the version already has.
    replace: bool = False


@router.post(
    "/models/{version_id}/paint",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def paint_model(
    version_id: uuid.UUID,
    body: PaintBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = painting.enqueue_paint(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        strokes=[stroke.model_dump(exclude_none=True) for stroke in body.strokes],
        base_colour=body.base_colour,
        label=body.label,
        replace=body.replace,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
