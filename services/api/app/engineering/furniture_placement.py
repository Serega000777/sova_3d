"""Fail-closed 2D furniture clearance checks for floor-plan placement."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.engineering.floor_plan import FloorPlan, Point


@dataclass(frozen=True, slots=True)
class FurnitureFootprint:
    id: str
    at: Point
    width_mm: float
    depth_mm: float
    rotation_deg: float


def _axes(rotation_deg: float) -> tuple[Point, Point]:
    angle = math.radians(rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    return (cosine, sine), (-sine, cosine)


def _corners(item: FurnitureFootprint, *, inflate_mm: float = 0.0) -> list[Point]:
    axis_x, axis_y = _axes(item.rotation_deg)
    half_x = item.width_mm / 2 + inflate_mm
    half_y = item.depth_mm / 2 + inflate_mm
    return [
        (
            item.at[0] + sign_x * half_x * axis_x[0] + sign_y * half_y * axis_y[0],
            item.at[1] + sign_x * half_x * axis_x[1] + sign_y * half_y * axis_y[1],
        )
        for sign_x, sign_y in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Even/odd containment; a point on an edge counts as inside."""
    inside = False
    x, y = point
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
        if abs(cross) <= 1e-7 and (
            min(a[0], b[0]) - 1e-7 <= x <= max(a[0], b[0]) + 1e-7
            and min(a[1], b[1]) - 1e-7 <= y <= max(a[1], b[1]) + 1e-7
        ):
            return True
        if (a[1] > y) != (b[1] > y):
            crossing_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < crossing_x:
                inside = not inside
    return inside


def _overlap(left: FurnitureFootprint, right: FurnitureFootprint, *, inflate_left: float) -> bool:
    """Separating-axis test for two oriented rectangles."""
    left_axes = _axes(left.rotation_deg)
    right_axes = _axes(right.rotation_deg)
    delta = (right.at[0] - left.at[0], right.at[1] - left.at[1])
    left_half = (left.width_mm / 2 + inflate_left, left.depth_mm / 2 + inflate_left)
    right_half = (right.width_mm / 2, right.depth_mm / 2)
    for axis in (*left_axes, *right_axes):
        distance = abs(delta[0] * axis[0] + delta[1] * axis[1])
        left_radius = sum(
            left_half[index] * abs(left_axes[index][0] * axis[0] + left_axes[index][1] * axis[1])
            for index in range(2)
        )
        right_radius = sum(
            right_half[index] * abs(right_axes[index][0] * axis[0] + right_axes[index][1] * axis[1])
            for index in range(2)
        )
        if distance >= left_radius + right_radius - 1e-7:
            return False
    return True


def _wall_footprint(index: int, a: Point, b: Point, thickness_mm: float) -> FurnitureFootprint:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return FurnitureFootprint(
        id=f"wall:{index}",
        at=((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
        width_mm=math.hypot(dx, dy),
        depth_mm=thickness_mm,
        rotation_deg=math.degrees(math.atan2(dy, dx)),
    )


def placement_conflict(
    plan: FloorPlan,
    candidate: FurnitureFootprint,
    *,
    clearance_mm: float,
    furniture: list[FurnitureFootprint],
) -> tuple[str, str] | None:
    """Return a stable conflict code/id, or ``None`` when the placement is valid."""
    values = (
        *candidate.at,
        candidate.width_mm,
        candidate.depth_mm,
        candidate.rotation_deg,
        clearance_mm,
    )
    if any(not math.isfinite(value) for value in values):
        return "invalid", candidate.id
    if candidate.width_mm <= 0 or candidate.depth_mm <= 0 or clearance_mm < 0:
        return "invalid", candidate.id
    envelope = _corners(candidate, inflate_mm=clearance_mm)
    if not plan.rooms or not any(
        all(_point_in_polygon(point, room.outline) for point in envelope) for room in plan.rooms
    ):
        return "outside_room", candidate.id
    for index, wall in enumerate(plan.walls):
        wall_item = _wall_footprint(index, wall.a, wall.b, wall.thickness_mm)
        if _overlap(candidate, wall_item, inflate_left=clearance_mm):
            return "wall_clearance", wall_item.id
    for obstacle in furniture:
        if obstacle.id != candidate.id and _overlap(candidate, obstacle, inflate_left=clearance_mm):
            return "furniture_clearance", obstacle.id
    return None
