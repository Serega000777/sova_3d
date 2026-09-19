"""Enclosures (T-157, F-036): the request becomes a job; the job builds the plan exactly."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.engineering import enclosure
from app.engineering.components import COMPONENTS
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.authz import require_workspace_role

ENCLOSURE_JOB = "build_enclosure"


def request_from(body: dict[str, Any]) -> enclosure.EnclosureRequest:
    component_id = str(body.get("component_id") or "")
    if component_id not in COMPONENTS:
        raise ValidationFailedError(
            f"unknown component {component_id!r}", {"hint": "GET /api/v1/components?q="}
        )
    component = COMPONENTS[component_id]
    if component.kind not in enclosure.HOUSED_KINDS:
        raise ValidationFailedError(
            f"{component.name} is not something a case is built around",
            {"kind": component.kind},
        )
    fan_id = body.get("fan_id")
    if fan_id and (fan_id not in COMPONENTS or COMPONENTS[fan_id].kind != "fan"):
        raise ValidationFailedError(f"unknown fan {fan_id!r}", {"fans": ["fan-30", "fan-40"]})
    return enclosure.EnclosureRequest(
        component_id=component_id,
        wall_mm=float(body.get("wall_mm") or 2.0),
        clearance_mm=float(body.get("clearance_mm") or 1.0),
        headroom_mm=float(body.get("headroom_mm") or 2.0),
        lid=bool(body.get("lid", True)),
        fan_id=str(fan_id) if fan_id else None,
        vents=bool(body.get("vents", True)),
        corner_radius_mm=float(body.get("corner_radius_mm", 2.0) or 0.0),
        material_id=body.get("material_id"),
    )


def enqueue_enclosure(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    request: enclosure.EnclosureRequest,
    project_id: uuid.UUID | None = None,
    label: str | None = None,
    ai_request_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> tuple[Job, uuid.UUID, enclosure.Enclosure]:
    """Build the plan now (so a bad request fails here, not in a job), then queue the kernel."""
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    built = enclosure.build(request)
    component = COMPONENTS[request.component_id]
    if idempotency_key:  # a retry must not leave a second, empty project behind
        existing = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace_id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None and existing.project_id is not None:
            return existing, existing.project_id, built
    if project_id is None:
        project = projects.create_project(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            name=label or f"{component.name} case",
            description=built.plan["goal"],
        )
        project_id = project.id
    else:
        projects.get_project(db, user_id=user_id, project_id=project_id)
    job = jobs.enqueue(
        db,
        workspace_id=workspace_id,
        job_type=ENCLOSURE_JOB,
        input={
            "project_id": str(project_id),
            "request": request.__dict__,
            "label": label or built.plan["goal"],
            "ai_request_id": str(ai_request_id) if ai_request_id else None,
        },
        created_by=user_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    return job, project_id, built
