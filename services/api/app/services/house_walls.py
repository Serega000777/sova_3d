"""Queue the freeform house-walls plan and attach its result to a project."""

from __future__ import annotations

import uuid
from dataclasses import asdict

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.engineering.house_walls import HouseWallsRequest
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.authz import require_workspace_role

HOUSE_WALLS_JOB = "build_house_walls"


def enqueue_house_walls(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    request: HouseWallsRequest,
    project_id: uuid.UUID | None = None,
    label: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Job, uuid.UUID]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    plan = request.build()
    if idempotency_key:
        existing = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace_id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None and existing.project_id is not None:
            return existing, existing.project_id
    if project_id is None:
        project = projects.create_project(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            name=label or "House design",
            description=plan.goal,
        )
        project_id = project.id
    else:
        projects.get_project(db, user_id=user_id, project_id=project_id)
    job = jobs.enqueue(
        db,
        workspace_id=workspace_id,
        job_type=HOUSE_WALLS_JOB,
        input={
            "project_id": str(project_id),
            "request": asdict(request),
            "label": label or plan.goal,
        },
        created_by=user_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    return job, project_id
