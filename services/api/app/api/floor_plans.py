"""Project floor-plan endpoint: the real plan derived from an immutable house version."""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.engineering.floor_plan import FloorPlan
from app.services.floor_plans import auto_layout_project_floor_plan
from app.services.floor_plans import (
    get_project_floor_plan as load_project_floor_plan,
)

router = APIRouter(tags=["floor-plans"])


@router.get("/projects/{project_id}/floor-plan", response_model=FloorPlan)
def get_project_floor_plan(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> FloorPlan:
    return load_project_floor_plan(
        db, user_id=principal.user_id, project_id=project_id
    ).plan


class FloorPlanLayoutBody(BaseModel):
    base_version_id: uuid.UUID
    room_count: int = Field(ge=2, le=8)
    partition_thickness_mm: float = Field(default=120, ge=60, le=300)
    door_width_mm: float = Field(default=900, ge=600, le=1_800)


class FloorPlanLayoutResult(BaseModel):
    version_id: uuid.UUID
    sequence_no: int
    floor_plan: FloorPlan


@router.post(
    "/projects/{project_id}/floor-plan/auto-layout",
    status_code=status.HTTP_201_CREATED,
    response_model=FloorPlanLayoutResult,
)
def auto_layout_floor_plan(
    project_id: uuid.UUID,
    body: FloorPlanLayoutBody,
    db: DbDep,
    principal: PrincipalDep,
) -> FloorPlanLayoutResult:
    result = auto_layout_project_floor_plan(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        base_version_id=body.base_version_id,
        room_count=body.room_count,
        partition_thickness_mm=body.partition_thickness_mm,
        door_width_mm=body.door_width_mm,
    )
    return FloorPlanLayoutResult(
        version_id=result.version.id,
        sequence_no=result.version.sequence_no,
        floor_plan=result.plan,
    )
