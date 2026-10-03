"""Freeform house-walls API: draw a closed perimeter, get back a fused 3D house shell."""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering.house_walls import HouseWallsRequest, PlanWallInput
from app.services import house_walls

router = APIRouter(tags=["house-design"])


class PlanWallBody(BaseModel):
    a: tuple[float, float]
    b: tuple[float, float]
    thickness_mm: float = Field(ge=60, le=600, default=120)


class HouseWallsBody(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)
    walls: list[PlanWallBody] = Field(min_length=3, max_length=256)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)


class HouseWallsAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    height_mm: float
    wall_count: int


@router.post(
    "/house-walls", status_code=status.HTTP_202_ACCEPTED, response_model=HouseWallsAccepted
)
def build_house_walls(
    body: HouseWallsBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> HouseWallsAccepted:
    try:
        request = HouseWallsRequest(
            walls=[PlanWallInput(a=w.a, b=w.b, thickness_mm=w.thickness_mm) for w in body.walls],
            floor_height_mm=body.floor_height_mm,
            floors=body.floors,
        )
    except ValidationError as exc:
        # Field bounds are already enforced by HouseWallsBody; what lands here is the domain
        # check (closed perimeter, per-wall length, total perimeter) that only a full plan can see.
        raise ValidationFailedError(str(exc.errors()[0].get("msg", exc))) from exc
    job, project_id = house_walls.enqueue_house_walls(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        request=request,
        project_id=body.project_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return HouseWallsAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        height_mm=request.floor_height_mm * request.floors,
        wall_count=len(request.walls),
    )
