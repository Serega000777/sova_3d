"""Printer-scale furniture placement checks shared by the API and job handler."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import ConflictError, ValidationFailedError
from app.engineering.floor_plan import FloorPlan
from app.engineering.furniture_placement import FurnitureFootprint, placement_conflict
from app.furniture_catalog import BY_KIND
from app.models.core import Project
from app.models.versioning import ProjectVersion
from app.services import scenes

AUTO_FURNISH_JOB = "auto_furnish_floor_plan"


def scene_footprints(
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


@dataclass(frozen=True, slots=True)
class PlannedFurniture:
    room_index: int
    room_name: str
    kind: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    width_mm: float
    depth_mm: float
    height_mm: float
    clearance_mm: float


_PRIMARY_FURNITURE = {
    "bedroom": "bed",
    "kitchen_living": "table",
    "living_room": "sofa",
    "bathroom": "cabinet",
    "entry": "cabinet",
    "office": "table",
    "nursery": "bed",
    "storage": "cabinet",
}


def plan_auto_furniture(
    plan: FloorPlan,
    *,
    existing: list[FurnitureFootprint],
    clearance_mm: float = 150.0,
) -> list[PlannedFurniture]:
    """Place one real catalogue item in every typed room, or reject the whole plan.

    The bounded 3x3 candidate grid deliberately favours the centre and then the corners.
    It uses the same oriented-rectangle collision predicate as manual drag placement, so a
    generated layout cannot bypass wall, room or existing-furniture clearance checks.
    """
    if not plan.rooms or any(room.kind is None for room in plan.rooms):
        raise ValidationFailedError("automatic furniture requires a type for every room")
    if clearance_mm < 0 or clearance_mm > 5_000:
        raise ValidationFailedError("automatic furniture clearance is outside the allowed range")

    occupied = list(existing)
    result: list[PlannedFurniture] = []
    wall_margin = max((wall.thickness_mm for wall in plan.walls), default=0.0) / 2
    for room_index, room in enumerate(plan.rooms):
        assert room.kind is not None
        kind = _PRIMARY_FURNITURE[room.kind]
        item = BY_KIND[kind]
        min_x = min(point[0] for point in room.outline)
        max_x = max(point[0] for point in room.outline)
        min_y = min(point[1] for point in room.outline)
        max_y = max(point[1] for point in room.outline)
        placed: PlannedFurniture | None = None
        for rotation_deg in (0.0, 90.0):
            width = float(item["width_mm"])
            depth = float(item["depth_mm"])
            span_x, span_y = (width, depth) if rotation_deg == 0 else (depth, width)
            margin_x = span_x / 2 + clearance_mm + wall_margin
            margin_y = span_y / 2 + clearance_mm + wall_margin
            xs = [(min_x + max_x) / 2, min_x + margin_x, max_x - margin_x]
            ys = [(min_y + max_y) / 2, min_y + margin_y, max_y - margin_y]
            for x_mm, y_mm in (
                (xs[0], ys[0]),
                (xs[1], ys[1]),
                (xs[2], ys[1]),
                (xs[1], ys[2]),
                (xs[2], ys[2]),
                (xs[0], ys[1]),
                (xs[0], ys[2]),
                (xs[1], ys[0]),
                (xs[2], ys[0]),
            ):
                candidate = FurnitureFootprint(
                    id=f"auto:{room_index}:{kind}",
                    at=(x_mm, y_mm),
                    width_mm=width,
                    depth_mm=depth,
                    rotation_deg=rotation_deg,
                )
                if (
                    placement_conflict(
                        plan,
                        candidate,
                        clearance_mm=clearance_mm,
                        furniture=occupied,
                    )
                    is not None
                ):
                    continue
                placed = PlannedFurniture(
                    room_index=room_index,
                    room_name=room.name,
                    kind=kind,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation_deg=rotation_deg,
                    width_mm=width,
                    depth_mm=depth,
                    height_mm=float(item["height_mm"]),
                    clearance_mm=clearance_mm,
                )
                occupied.append(candidate)
                break
            if placed is not None:
                break
        if placed is None:
            raise ValidationFailedError(
                "automatic furniture does not fit a requested room",
                {"room_index": room_index, "room_name": room.name, "kind": kind},
            )
        result.append(placed)
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
        furniture=scene_footprints(db, version=version, workspace_id=project.workspace_id),
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
