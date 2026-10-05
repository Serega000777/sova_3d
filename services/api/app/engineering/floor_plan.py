"""Deterministic 2D plans derived from house-design inputs.

The 3D house builders already know the exact footprint in millimetres.  Keeping the
derived plan beside the immutable project version makes the plan/markup workspace use
the user's real house instead of a demo or a browser-only JSON file.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest, ordered_wall_outline

Point = tuple[float, float]


class PlanWall(BaseModel):
    a: Point
    b: Point
    thickness_mm: float = Field(gt=0, le=2_000)


class PlanOpening(BaseModel):
    wall: int = Field(ge=0)
    offset_mm: float = Field(ge=0)
    width_mm: float = Field(gt=0)
    kind: str = Field(pattern="^(door|window)$")


class PlanRoom(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    outline: list[Point] = Field(min_length=3, max_length=1_024)


class FloorPlan(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    walls: list[PlanWall] = Field(default_factory=list, max_length=1_024)
    openings: list[PlanOpening] = Field(default_factory=list, max_length=1_024)
    rooms: list[PlanRoom] = Field(default_factory=list, max_length=512)


def _walls_from_outline(outline: list[Point], thickness_mm: float) -> list[PlanWall]:
    return [
        PlanWall(a=point, b=outline[(index + 1) % len(outline)], thickness_mm=thickness_mm)
        for index, point in enumerate(outline)
    ]


def floor_plan_from_house_box(
    request: HouseBoxRequest, *, plan_id: str, name: str
) -> FloorPlan:
    """Project the deterministic massing shape onto the ground plane."""
    length = float(request.length_mm)
    width = float(request.width_mm)
    if request.shape == "rectangle":
        outline: list[Point] = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]
    elif request.shape == "l_shape":
        outline = [
            (0.0, 0.0),
            (length, 0.0),
            (length, width / 2),
            (length / 2, width / 2),
            (length / 2, width),
            (0.0, width),
        ]
    else:
        third = length / 3
        outline = [
            (third, 0.0),
            (2 * third, 0.0),
            (2 * third, 2 * width / 3),
            (length, 2 * width / 3),
            (length, width),
            (0.0, width),
            (0.0, 2 * width / 3),
            (third, 2 * width / 3),
        ]
    return FloorPlan(
        id=plan_id,
        name=name,
        walls=_walls_from_outline(outline, 250.0),
        rooms=[PlanRoom(name="Footprint", outline=outline)],
    )


def floor_plan_from_house_walls(
    request: HouseWallsRequest, *, plan_id: str, name: str
) -> FloorPlan:
    """Keep the exact drawn wall centre-lines and derive their single closed room outline."""
    outline = ordered_wall_outline(request.walls)
    return FloorPlan(
        id=plan_id,
        name=name,
        walls=[
            PlanWall(a=wall.a, b=wall.b, thickness_mm=float(wall.thickness_mm))
            for wall in request.walls
        ],
        rooms=[PlanRoom(name="House", outline=outline)],
    )


def _rectangular_bounds(plan: FloorPlan) -> tuple[float, float, float, float]:
    points = [point for room in plan.rooms for point in room.outline]
    if not points:
        raise ValueError("automatic room layout currently requires a rectangular footprint")
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    rectangle_area = (max_x - min_x) * (max_y - min_y)
    rooms_area = sum(
        abs(
            sum(
                point[0] * room.outline[(index + 1) % len(room.outline)][1]
                - room.outline[(index + 1) % len(room.outline)][0] * point[1]
                for index, point in enumerate(room.outline)
            )
            / 2
        )
        for room in plan.rooms
    )
    if rectangle_area <= 0 or not math.isclose(
        rooms_area, rectangle_area, rel_tol=1e-9, abs_tol=1.0
    ):
        raise ValueError("automatic room layout currently requires an axis-aligned rectangle")
    return min_x, min_y, max_x, max_y


def auto_layout_rectangular_plan(
    plan: FloorPlan,
    *,
    room_count: int,
    partition_thickness_mm: float = 120.0,
    door_width_mm: float = 900.0,
) -> FloorPlan:
    """Split a rectangular footprint into connected rooms with one door per partition.

    The first deterministic layout is intentionally modest: equal strips along the footprint's
    longer axis.  Irregular/L/T footprints are refused instead of receiving a geometrically
    misleading layout; later layout engines can extend the same immutable-plan API.
    """
    if room_count < 2 or room_count > 8:
        raise ValueError("room_count must be between 2 and 8")
    if partition_thickness_mm < 60 or partition_thickness_mm > 300:
        raise ValueError("partition_thickness_mm must be between 60 and 300")
    if door_width_mm < 600 or door_width_mm > 1_800:
        raise ValueError("door_width_mm must be between 600 and 1800")

    min_x, min_y, max_x, max_y = _rectangular_bounds(plan)
    width = max_x - min_x
    depth = max_y - min_y
    split_x = width >= depth
    split_span = width if split_x else depth
    partition_length = depth if split_x else width
    if split_span / room_count < 2_000:
        raise ValueError("the footprint is too small for that many rooms of at least 2000 mm")
    if partition_length < door_width_mm + 400:
        raise ValueError("the partition is too short for the requested door width")

    epsilon = 1e-6

    def exterior(wall: PlanWall) -> bool:
        if math.isclose(wall.a[0], wall.b[0], abs_tol=epsilon):
            return math.isclose(wall.a[0], min_x, abs_tol=epsilon) or math.isclose(
                wall.a[0], max_x, abs_tol=epsilon
            )
        if math.isclose(wall.a[1], wall.b[1], abs_tol=epsilon):
            return math.isclose(wall.a[1], min_y, abs_tol=epsilon) or math.isclose(
                wall.a[1], max_y, abs_tol=epsilon
            )
        return False

    outer_indices = [index for index, wall in enumerate(plan.walls) if exterior(wall)]
    if len(outer_indices) != 4:
        raise ValueError("the rectangular footprint must have exactly four exterior walls")
    outer_walls = [plan.walls[index] for index in outer_indices]
    remap = {old: new for new, old in enumerate(outer_indices)}
    openings = [
        opening.model_copy(update={"wall": remap[opening.wall]})
        for opening in plan.openings
        if opening.wall in remap
    ]
    rooms: list[PlanRoom] = []
    partitions: list[PlanWall] = []
    step = split_span / room_count

    for index in range(room_count):
        low = (min_x if split_x else min_y) + step * index
        high = (min_x if split_x else min_y) + step * (index + 1)
        if split_x:
            outline = [(low, min_y), (high, min_y), (high, max_y), (low, max_y)]
        else:
            outline = [(min_x, low), (max_x, low), (max_x, high), (min_x, high)]
        rooms.append(PlanRoom(name=f"Room {index + 1}", outline=outline))
        if index == room_count - 1:
            continue
        cut = high
        wall = (
            PlanWall(
                a=(cut, min_y),
                b=(cut, max_y),
                thickness_mm=partition_thickness_mm,
            )
            if split_x
            else PlanWall(
                a=(min_x, cut),
                b=(max_x, cut),
                thickness_mm=partition_thickness_mm,
            )
        )
        partitions.append(wall)
        openings.append(
            PlanOpening(
                wall=len(outer_walls) + len(partitions) - 1,
                offset_mm=(partition_length - door_width_mm) / 2,
                width_mm=door_width_mm,
                kind="door",
            )
        )

    return plan.model_copy(
        update={"walls": [*outer_walls, *partitions], "openings": openings, "rooms": rooms}
    )
