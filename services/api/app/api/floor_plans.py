"""Project floor-plan endpoint: the real plan derived from an immutable house version."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.engineering.floor_plan import BuildingFloorPlans, FloorPlan, RoomRequirement
from app.models.core import Project
from app.services import furniture as furniture_service
from app.services import jobs
from app.services.floor_plans import auto_layout_project_floor_plan, edit_room_plan_wall
from app.services.floor_plans import (
    get_project_floor_plan as load_project_floor_plan,
)
from app.services.floor_plans import get_project_floor_plans as load_project_floor_plans

router = APIRouter(tags=["floor-plans"])


@router.get("/projects/{project_id}/floor-plan", response_model=FloorPlan)
def get_project_floor_plan(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> FloorPlan:
    return load_project_floor_plan(db, user_id=principal.user_id, project_id=project_id).plan


@router.get("/projects/{project_id}/floor-plans", response_model=BuildingFloorPlans)
def get_project_floor_plans(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> BuildingFloorPlans:
    return load_project_floor_plans(db, user_id=principal.user_id, project_id=project_id)


class FloorPlanLayoutBody(BaseModel):
    base_version_id: uuid.UUID
    floor_index: int = Field(default=0, ge=0, le=2)
    room_count: int = Field(ge=2, le=8)
    partition_thickness_mm: float = Field(default=120, ge=60, le=300)
    door_width_mm: float = Field(default=900, ge=600, le=1_800)
    room_requirements: list[RoomRequirement] | None = Field(
        default=None, min_length=2, max_length=8
    )
    auto_furnish: bool = False

    @model_validator(mode="after")
    def typed_composition_is_complete(self) -> FloorPlanLayoutBody:
        if self.room_requirements is not None and len(self.room_requirements) != self.room_count:
            raise ValueError("room_count must match room_requirements")
        if self.auto_furnish and self.room_requirements is None:
            raise ValueError("auto_furnish requires room_requirements")
        return self


class FloorPlanLayoutResult(BaseModel):
    version_id: uuid.UUID
    sequence_no: int
    floor_plan: FloorPlan
    furniture_job_id: uuid.UUID | None = None


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
        room_requirements=body.room_requirements,
        floor_index=body.floor_index,
        auto_furnish=body.auto_furnish,
    )
    furniture_job_id: uuid.UUID | None = None
    if body.auto_furnish:
        project = db.get(Project, result.version.project_id)
        assert project is not None
        placements = furniture_service.plan_auto_furniture(
            result.plan,
            existing=furniture_service.scene_footprints(
                db, version=result.version, workspace_id=project.workspace_id
            ),
        )
        job = jobs.enqueue(
            db,
            workspace_id=project.workspace_id,
            project_id=project.id,
            project_version_id=result.version.id,
            job_type=furniture_service.AUTO_FURNISH_JOB,
            input={
                "version_id": str(result.version.id),
                "floor_plan_id": result.plan.id,
                "floor_plan": result.plan.model_dump(mode="json"),
                "placements": [asdict(item) for item in placements],
            },
            created_by=principal.user_id,
        )
        furniture_job_id = job.id
    return FloorPlanLayoutResult(
        version_id=result.version.id,
        sequence_no=result.version.sequence_no,
        floor_plan=result.plan,
        furniture_job_id=furniture_job_id,
    )


class RoomWallEditBody(BaseModel):
    base_version_id: uuid.UUID
    wall_index: int = Field(ge=0, le=1_023)
    offset_mm: float = Field(ge=-5_000, le=5_000)
    thickness_mm: float = Field(ge=20, le=2_000)
    height_mm: float = Field(ge=500, le=12_000)
    material_id: str | None = Field(default=None, pattern=r"^[a-z0-9_.-]{1,120}$")


@router.post(
    "/projects/{project_id}/floor-plan/walls/edit",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def edit_room_wall(
    project_id: uuid.UUID,
    body: RoomWallEditBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = edit_room_plan_wall(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        base_version_id=body.base_version_id,
        wall_index=body.wall_index,
        offset_mm=body.offset_mm,
        thickness_mm=body.thickness_mm,
        height_mm=body.height_mm,
        material_id=body.material_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
