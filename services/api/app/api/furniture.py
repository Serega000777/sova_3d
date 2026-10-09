"""Furniture catalogue and immutable scene placement endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.furniture_catalog import BY_KIND, CATALOG
from app.models.core import WorkspaceRole
from app.services import jobs, projects
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
        "width_mm": body.width_mm or default["width_mm"],
        "depth_mm": body.depth_mm or default["depth_mm"],
        "height_mm": body.height_mm or default["height_mm"],
    }
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
        },
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
