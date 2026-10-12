"""Furniture catalogue and immutable scene placement endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.furniture_catalog import BY_KIND, CATALOG
from app.models.core import WorkspaceRole
from app.services import floor_plans, jobs, projects
from app.services import furniture as furniture_service
from app.services.authz import require_workspace_role

router = APIRouter(tags=["furniture"])
FurnitureKind = Literal["chair", "table", "sofa", "bed", "cabinet"]


class FurnitureItem(BaseModel):
    kind: FurnitureKind
    name: str
    name_ru: str
    width_mm: float
    depth_mm: float
    height_mm: float


class FurniturePlacement(BaseModel):
    kind: FurnitureKind
    x_mm: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    y_mm: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    z_mm: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    rotation_deg: float = Field(default=0, ge=-360_000, le=360_000)
    width_mm: float | None = Field(default=None, ge=100, le=10_000)
    depth_mm: float | None = Field(default=None, ge=100, le=10_000)
    height_mm: float | None = Field(default=None, ge=100, le=10_000)
    # 2D drag-to-place sends both fields. Omitting both preserves unrestricted 3D placement.
    floor_plan_id: str | None = Field(default=None, min_length=1, max_length=200)
    clearance_mm: float | None = Field(default=None, ge=0, le=5_000)


@router.get("/furniture", response_model=list[FurnitureItem])
def list_furniture(principal: PrincipalDep) -> list[FurnitureItem]:
    del principal
    return [FurnitureItem.model_validate(item) for item in CATALOG]


@router.post(
    "/models/{version_id}/furniture",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def place_furniture(
    version_id: uuid.UUID,
    body: FurniturePlacement,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    default = BY_KIND[body.kind]
    dimensions = {
        "width_mm": body.width_mm if body.width_mm is not None else default["width_mm"],
        "depth_mm": body.depth_mm if body.depth_mm is not None else default["depth_mm"],
        "height_mm": body.height_mm if body.height_mm is not None else default["height_mm"],
    }
    if (body.floor_plan_id is None) != (body.clearance_mm is None):
        raise ValidationFailedError("floor_plan_id and clearance_mm must be provided together")
    job_plan: dict[str, object] | None = None
    if body.clearance_mm is not None and body.floor_plan_id is not None:
        record = floor_plans.get_project_floor_plan(
            db, user_id=principal.user_id, project_id=project.id
        )
        furniture_service.validate_plan_placement(
            db,
            project=project,
            version=version,
            plan=record.plan,
            floor_plan_id=body.floor_plan_id,
            kind=body.kind,
            x_mm=body.x_mm,
            y_mm=body.y_mm,
            width_mm=dimensions["width_mm"],
            depth_mm=dimensions["depth_mm"],
            rotation_deg=body.rotation_deg,
            clearance_mm=body.clearance_mm,
        )
        job_plan = record.plan.model_dump(mode="json")
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type="place_furniture",
        input={
            "version_id": str(version.id),
            "kind": body.kind,
            **dimensions,
            "x_mm": body.x_mm,
            "y_mm": body.y_mm,
            "z_mm": body.z_mm,
            "rotation_deg": body.rotation_deg,
            "floor_plan_id": body.floor_plan_id,
            "clearance_mm": body.clearance_mm,
            "floor_plan": job_plan,
        },
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
