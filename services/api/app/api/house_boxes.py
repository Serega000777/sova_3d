"""Quick-start house massing wizard API."""

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering.house_box import HouseBoxRequest, StraightStairRequest
from app.interior_materials import material_by_id
from app.services import house_boxes

router = APIRouter(tags=["house-design"])


class StraightStairBody(BaseModel):
    width_mm: float = Field(default=1_000, ge=700, le=2_000)
    tread_depth_mm: float = Field(default=280, ge=200, le=400)
    step_count: int = Field(default=17, ge=10, le=30)
    placement: Literal["left", "center", "right"] = "center"
    railing: bool = True
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class HouseBoxBody(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)
    length_mm: float = Field(ge=2_000, le=50_000)
    width_mm: float = Field(ge=2_000, le=50_000)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)
    shape: Literal["rectangle", "l_shape", "t_shape"] = "rectangle"
    stair: StraightStairBody | None = None


class HouseBoxAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    height_mm: float
    shape: Literal["rectangle", "l_shape", "t_shape"]


@router.post("/house-boxes", status_code=status.HTTP_202_ACCEPTED, response_model=HouseBoxAccepted)
def build_house_box(
    body: HouseBoxBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> HouseBoxAccepted:
    if body.stair is not None and body.stair.material_id is not None:
        material_by_id(body.stair.material_id)
    try:
        request = HouseBoxRequest(
            length_mm=body.length_mm,
            width_mm=body.width_mm,
            floor_height_mm=body.floor_height_mm,
            floors=body.floors,
            shape=body.shape,
            stair=(
                StraightStairRequest(**body.stair.model_dump()) if body.stair is not None else None
            ),
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    job, project_id = house_boxes.enqueue_house_box(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        request=request,
        project_id=body.project_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return HouseBoxAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        height_mm=request.floor_height_mm * request.floors,
        shape=request.shape,
    )
