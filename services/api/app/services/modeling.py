"""Deterministic primitives for starting a model without an AI prompt (T-173, F-061)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.api.errors import ConflictError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.references import ProjectReference
from app.services import jobs, projects
from app.services.authz import require_workspace_role
from app.services.calibration import EXECUTE_PLAN_JOB


def primitive_plan(
    *,
    kind: Literal["box", "cylinder", "sphere", "cone", "torus"],
    width_mm: float | None = None,
    depth_mm: float | None = None,
    height_mm: float | None = None,
    diameter_mm: float | None = None,
    top_diameter_mm: float | None = None,
    outer_diameter_mm: float | None = None,
    tube_diameter_mm: float | None = None,
    axis: Literal["x", "y", "z"] = "z",
    centered: bool = True,
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
            "centered": centered,
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
            "axis": axis,
            "origin_mm": _axial_origin(axis, height_mm, centered),
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
    elif kind == "cone":
        assert diameter_mm is not None and height_mm is not None
        top = top_diameter_mm or 0.0
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_cone",
            "bottom_diameter_mm": diameter_mm,
            "top_diameter_mm": top,
            "height_mm": height_mm,
            "axis": axis,
            "origin_mm": _axial_origin(axis, height_mm, centered),
        }
        label = f"Cone Ø{diameter_mm:g}/Ø{top:g}×{height_mm:g} mm"
    else:
        assert outer_diameter_mm is not None and tube_diameter_mm is not None
        operation = {
            "schema_version": 1,
            "id": "body",
            "type": "create_torus",
            "outer_diameter_mm": outer_diameter_mm,
            "tube_diameter_mm": tube_diameter_mm,
            "axis": axis,
        }
        label = f"Ring Ø{outer_diameter_mm:g}, tube Ø{tube_diameter_mm:g} mm"
    return parse_plan(
        {
            "schema_version": 1,
            "goal": label,
            "operations": [operation],
            "validation_steps": ["one valid closed parametric solid"],
            "expected_outputs": ["body"],
        }
    )


def _axial_origin(axis: Literal["x", "y", "z"], height_mm: float, centered: bool) -> list[float]:
    """Return the base-centre expected by axial primitives from a UI centre."""
    origin = [0.0, 0.0, 0.0]
    if centered:
        origin[{"x": 0, "y": 1, "z": 2}[axis]] = -height_mm / 2
    return origin


def start_with_primitive(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    plan: OperationPlan,
    idempotency_key: str | None = None,
    provenance: dict[str, Any] | None = None,
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
            "provenance": provenance or {"created_with": "primitive_tool"},
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )


def dimensioned_drawing_plan(
    *,
    width_mm: float,
    height_mm: float,
    thickness_mm: float,
    corner_radius_mm: float,
    holes: list[dict[str, float]],
) -> OperationPlan:
    """Build an exact plate from dimensions manually traced over a calibrated drawing."""
    half_width = width_mm / 2
    half_height = height_mm / 2
    radius = corner_radius_mm
    if radius > 0:
        points = [
            (-half_width + radius, -half_height),
            (half_width - radius, -half_height),
            (half_width, -half_height + radius),
            (half_width, half_height - radius),
            (half_width - radius, half_height),
            (-half_width + radius, half_height),
            (-half_width, half_height - radius),
            (-half_width, -half_height + radius),
        ]
        segments = [
            {"kind": "line"},
            {"kind": "arc", "center_mm": (half_width - radius, -half_height + radius)},
            {"kind": "line"},
            {"kind": "arc", "center_mm": (half_width - radius, half_height - radius)},
            {"kind": "line"},
            {"kind": "arc", "center_mm": (-half_width + radius, half_height - radius)},
            {"kind": "line"},
            {"kind": "arc", "center_mm": (-half_width + radius, -half_height + radius)},
        ]
    else:
        points = [
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        ]
        segments = [{"kind": "line"} for _ in points]

    operations: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "id": "body",
            "type": "extrude",
            "profile": {
                "kind": "sketch",
                "points_mm": points,
                "segments": segments,
                "constraints": [{"kind": "fixed", "point": 0}],
                "tolerance_mm": 1e-5,
            },
            "height_mm": thickness_mm,
        }
    ]
    for index, hole in enumerate(holes):
        operations.append(
            {
                "schema_version": 1,
                "id": f"drawing_hole_{index + 1}",
                "type": "add_hole",
                "target": "body",
                "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
                "position_mm": [hole["x_mm"], hole["y_mm"]],
                "diameter_mm": hole["diameter_mm"],
            }
        )
    return parse_plan(
        {
            "schema_version": 1,
            "goal": (
                f"Dimensioned drawing {width_mm:g}×{height_mm:g}×{thickness_mm:g} mm, "
                f"R{corner_radius_mm:g}, {len(holes)} hole(s)"
            ),
            "operations": operations,
            "validation_steps": [
                "one closed exact extruded solid",
                "every declared through-hole is inside the traced outline",
            ],
            "expected_outputs": ["body"],
        }
    )


def start_from_dimensioned_drawing(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    plan: OperationPlan,
    trace: dict[str, Any],
    idempotency_key: str | None = None,
) -> Job:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    reference = db.get(ProjectReference, project.id)
    if reference is None:
        raise ConflictError("attach and calibrate the dimensioned drawing first")
    known_mm = (reference.settings or {}).get("known_mm")
    if not isinstance(known_mm, (int, float)) or known_mm <= 0:
        raise ConflictError("the dimensioned drawing needs a calibrated known length")
    return start_with_primitive(
        db,
        user_id=user_id,
        project_id=project.id,
        plan=plan,
        idempotency_key=idempotency_key,
        provenance={
            "created_with": "dimensioned_drawing_trace",
            "drawing_trace": {
                "schema_version": 1,
                "source_asset_id": str(reference.asset_id),
                "known_mm": float(known_mm),
                **trace,
            },
        },
    )
