"""Bounded functional mechanism generation (F-037/F-038)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.services import jobs, projects
from app.services.authz import require_workspace_role

router = APIRouter(tags=["mechanisms"])
HINGED_LID_JOB = "build_hinged_lid"


class HingedLidBody(BaseModel):
    width_mm: float = Field(default=100, ge=40, le=500)
    depth_mm: float = Field(default=70, ge=30, le=500)
    base_height_mm: float = Field(default=18, ge=8, le=200)
    lid_thickness_mm: float = Field(default=4, ge=2, le=30)
    pin_diameter_mm: float = Field(default=4, ge=2, le=20)
    clearance_mm: float = Field(default=0.3, ge=0.1, le=1.0)
    max_angle_deg: float = Field(default=110, ge=30, le=180)

    @model_validator(mode="after")
    def hinge_fits(self) -> HingedLidBody:
        outer_radius = self.pin_diameter_mm / 2 + self.clearance_mm + max(
            1.2, self.pin_diameter_mm * 0.3
        )
        if self.base_height_mm < outer_radius * 1.1:
            raise ValueError("base_height_mm is too small for the requested pin and clearance")
        return self


@router.post(
    "/models/{version_id}/mechanisms/hinged-lid",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def build_hinged_lid(
    version_id: uuid.UUID,
    body: HingedLidBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=HINGED_LID_JOB,
        input={"version_id": str(version.id), "spec": body.model_dump(mode="json")},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
