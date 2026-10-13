"""Immutable site composition around an exact house-box lineage."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.services import jobs, projects, site_plans
from app.services.authz import require_workspace_role

router = APIRouter(tags=["site-plan"])
Point2 = Annotated[list[float], Field(min_length=2, max_length=2)]
FenceSide = Literal["north", "east", "south", "west"]


def _flat_elevations() -> list[float]:
    return [0.0, 0.0, 0.0, 0.0]


def _all_fence_sides() -> list[FenceSide]:
    return ["north", "east", "south", "west"]


class SitePlanBody(BaseModel):
    plot_length_mm: float = Field(ge=5_000, le=200_000)
    plot_width_mm: float = Field(ge=5_000, le=200_000)
    corner_elevations_mm: Annotated[list[float], Field(min_length=4, max_length=4)] = Field(
        default_factory=_flat_elevations
    )
    house_x_mm: float = Field(default=0, ge=-100_000, le=100_000)
    house_y_mm: float = Field(default=0, ge=-100_000, le=100_000)
    house_rotation_deg: float = Field(default=0, ge=-180, le=180)
    path_points_mm: Annotated[list[Point2], Field(min_length=2, max_length=16)]
    path_width_mm: float = Field(default=1_200, ge=300, le=5_000)
    fence_sides: list[FenceSide] = Field(default_factory=_all_fence_sides, max_length=4)
    fence_height_mm: float = Field(default=1_500, ge=400, le=4_000)
    fence_post_spacing_mm: float = Field(default=2_500, ge=1_000, le=5_000)


@router.post(
    "/models/{version_id}/site-plan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def compose_site_plan(
    version_id: uuid.UUID,
    body: SitePlanBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    spec = body.model_dump(mode="json")
    site_plans.validate_spec(project=project, version=version, spec=spec)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=site_plans.SITE_PLAN_JOB,
        input={"version_id": str(version.id), "spec": spec},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
