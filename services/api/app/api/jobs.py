"""Long-running operations: POST /models/{version_id}/repair (T-031), GET /jobs/{id}."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.models.execution import FailureClass, JobStatus
from app.services import jobs, projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.authz import require_workspace_role

router = APIRouter(tags=["jobs"])


class JobOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None
    project_version_id: uuid.UUID | None
    type: str
    status: JobStatus
    progress: int
    stage: str | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    failure_class: FailureClass | None
    attempts: int
    cancel_requested: bool
    timeout_seconds: int
    cost_usd: Decimal
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


@router.post(
    "/models/{version_id}/repair",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def repair_model(
    version_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)

    asset = model_asset_of(db, version)
    if asset is None or asset.format not in REPAIRABLE_FORMATS:
        raise ValidationFailedError(
            "version has no repairable mesh asset",
            {"repairable_formats": sorted(REPAIRABLE_FORMATS)},
        )
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type="repair",
        input={"version_id": str(version.id), "asset_id": str(asset.id)},
        created_by=principal.user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> JobOut:
    return JobOut.model_validate(jobs.get_job(db, user_id=principal.user_id, job_id=job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> JobOut:
    """T-095: ask a job to stop. Work that has not started stops now; work in flight stops
    at its next checkpoint, so nothing is left half-written."""
    return JobOut.model_validate(jobs.request_cancel(db, user_id=principal.user_id, job_id=job_id))
