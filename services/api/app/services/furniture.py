"""Printer-scale furniture placement checks shared by the API and job handler."""

from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import ConflictError, ValidationFailedError
from app.engineering.floor_plan import FloorPlan
from app.engineering.furniture_placement import FurnitureFootprint, placement_conflict
from app.models.core import Project
from app.models.versioning import ProjectVersion
from app.services import scenes


def _scene_footprints(
    db: Session, *, version: ProjectVersion, workspace_id: uuid.UUID
) -> list[FurnitureFootprint]:
    result: list[FurnitureFootprint] = []
    for node in scenes.resolve_scene(db, version=version, workspace_id=workspace_id):
        footprint = node.get("footprint_mm")
        if (
            node.get("kind") != "object"
            or not node.get("effective_visible")
            or not isinstance(footprint, list)
            or len(footprint) != 2
        ):
            continue
        matrix = node["world_transform"]
        axis_x = (float(matrix[0][0]), float(matrix[1][0]))
        axis_y = (float(matrix[0][1]), float(matrix[1][1]))
        scale_x = math.hypot(*axis_x)
        scale_y = math.hypot(*axis_y)
        dot = axis_x[0] * axis_y[0] + axis_x[1] * axis_y[1]
        if scale_x <= 1e-9 or scale_y <= 1e-9 or abs(dot) > 1e-7 * scale_x * scale_y:
            raise ValidationFailedError(
                "furniture clearance needs a non-sheared XY scene transform",
                {"scene_node_id": node["id"]},
            )
        result.append(
            FurnitureFootprint(
                id=str(node["id"]),
                at=(float(matrix[0][3]), float(matrix[1][3])),
                width_mm=float(footprint[0]) * scale_x,
                depth_mm=float(footprint[1]) * scale_y,
                rotation_deg=math.degrees(math.atan2(axis_x[1], axis_x[0])),
            )
        )
    return result


def validate_plan_placement(
    db: Session,
    *,
    project: Project,
    version: ProjectVersion,
    plan: FloorPlan,
    floor_plan_id: str,
    kind: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    rotation_deg: float,
    clearance_mm: float,
) -> None:
    """Reject stale, outside-room and colliding 2D drag placements before geometry work."""
    if project.head_version_id != version.id:
        raise ConflictError(
            "the project changed; reload the plan before placing furniture",
            {"head_version_id": str(project.head_version_id)},
        )
    if floor_plan_id != plan.id:
        raise ConflictError(
            "the floor plan changed; reload before placing furniture",
            {"floor_plan_id": plan.id},
        )
    candidate = FurnitureFootprint(
        id=f"new:{kind}",
        at=(x_mm, y_mm),
        width_mm=width_mm,
        depth_mm=depth_mm,
        rotation_deg=rotation_deg,
    )
    conflict = placement_conflict(
        plan,
        candidate,
        clearance_mm=clearance_mm,
        furniture=_scene_footprints(db, version=version, workspace_id=project.workspace_id),
    )
    if conflict is None:
        return
    code, obstacle_id = conflict
    messages = {
        "invalid": "the furniture placement is invalid",
        "outside_room": "the furniture and its clearance must stay inside one room",
        "wall_clearance": "the furniture is too close to a wall",
        "furniture_clearance": "the furniture is too close to another item",
    }
    raise ValidationFailedError(
        messages.get(code, "the furniture placement conflicts with the floor plan"),
        {
            "placement_conflict": code,
            "obstacle_id": obstacle_id,
            "clearance_mm": clearance_mm,
        },
    )


def placement_plan(value: Any, *, expected_id: str) -> FloorPlan:
    """Parse the canonical plan copied into an internal job, failing closed if it changed."""
    try:
        plan = FloorPlan.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError("the furniture job has an invalid floor plan") from exc
    if plan.id != expected_id:
        raise ValidationFailedError("the furniture job floor plan id does not match")
    return plan
