"""Deterministic primitives for starting a model without an AI prompt (T-173, F-061)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.api.errors import ConflictError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.authz import require_workspace_role
from app.services.calibration import EXECUTE_PLAN_JOB


def primitive_plan(
    *,
    kind: Literal["box", "cylinder", "sphere", "cone"],
    width_mm: float | None = None,
    depth_mm: float | None = None,
    height_mm: float | None = None,
    diameter_mm: float | None = None,
    top_diameter_mm: float | None = None,
) -> OperationPlan:
    operation: dict[str, Any]
    label: str
    if kind == "box":
        assert width_mm is not None and depth_mm is not None and height_mm is not None
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_box",
            "width_mm": width_mm,
            "depth_mm": depth_mm,
            "height_mm": height_mm,
        }
        label = f"Box {width_mm:g}×{depth_mm:g}×{height_mm:g} mm"
    elif kind == "cylinder":
        assert diameter_mm is not None
        assert height_mm is not None
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_cylinder",
            "diameter_mm": diameter_mm,
            "height_mm": height_mm,
            "axis": "z",
        }
        label = f"Cylinder Ø{diameter_mm:g}×{height_mm:g} mm"
    elif kind == "sphere":
        assert diameter_mm is not None
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_sphere",
            "diameter_mm": diameter_mm,
        }
        label = f"Sphere Ø{diameter_mm:g} mm"
    else:
        assert diameter_mm is not None and height_mm is not None
        top = top_diameter_mm or 0.0
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_cone",
            "bottom_diameter_mm": diameter_mm,
            "top_diameter_mm": top,
            "height_mm": height_mm,
            "axis": "z",
        }
        label = f"Cone Ø{diameter_mm:g}/Ø{top:g}×{height_mm:g} mm"
    return parse_plan(
        {
            "schema_version": 1,
            "goal": label,
            "operations": [operation],
            "validation_steps": ["one valid closed parametric solid"],
            "expected_outputs": ["body"],
        }
    )


def start_with_primitive(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    plan: OperationPlan,
    idempotency_key: str | None = None,
) -> Job:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if project.head_version_id is not None:
        raise ConflictError(
            "the project already has a model; add the primitive as an edit",
            {"head_version_id": str(project.head_version_id)},
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=EXECUTE_PLAN_JOB,
        input={
            "project_id": str(project.id),
            "plan": plan.model_dump(mode="json"),
            "label": plan.goal,
            "provenance": {"created_with": "primitive_tool"},
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )
