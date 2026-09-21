"""Manual modeling tools (T-173, F-061)."""

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import modeling

router = APIRouter(tags=["modeling"])


class PrimitiveBody(BaseModel):
    kind: Literal["box", "cylinder", "sphere", "cone", "torus"]
    width_mm: float | None = Field(default=None, gt=0, le=100000)
    depth_mm: float | None = Field(default=None, gt=0, le=100000)
    height_mm: float | None = Field(default=None, gt=0, le=100000)
    diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    top_diameter_mm: float | None = Field(default=None, ge=0, le=100000)
    outer_diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    tube_diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    axis: Literal["x", "y", "z"] = "z"
    centered: bool = True

    @model_validator(mode="after")
    def dimensions_for_shape(self) -> "PrimitiveBody":
        if self.kind == "box" and (self.width_mm is None or self.depth_mm is None):
            raise ValueError("a box needs width_mm and depth_mm")
        if self.kind in {"box", "cylinder", "cone"} and self.height_mm is None:
            raise ValueError(f"a {self.kind} needs height_mm")
        if self.kind in {"cylinder", "sphere", "cone"} and self.diameter_mm is None:
            raise ValueError(f"a {self.kind} needs diameter_mm")
        if self.kind == "torus":
            if self.outer_diameter_mm is None or self.tube_diameter_mm is None:
                raise ValueError("a torus needs outer_diameter_mm and tube_diameter_mm")
            if 2 * self.tube_diameter_mm >= self.outer_diameter_mm:
                raise ValueError("tube diameter must be less than half the outer diameter")
        return self


@router.post(
    "/projects/{project_id}/primitives",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_primitive(
    project_id: uuid.UUID,
    body: PrimitiveBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    plan = modeling.primitive_plan(**body.model_dump())
    job = modeling.start_with_primitive(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        plan=plan,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
