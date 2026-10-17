"""Deterministic 2D plans derived from house-design inputs.

The 3D house builders already know the exact footprint in millimetres.  Keeping the
derived plan beside the immutable project version makes the plan/markup workspace use
the user's real house instead of a demo or a browser-only JSON file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.engineering.house_box import HouseBoxRequest, _stair_origin
from app.engineering.house_walls import HouseWallsRequest, ordered_wall_outline

Point = tuple[float, float]
RoomKind = Literal[
    "bedroom",
    "kitchen_living",
    "living_room",
    "bathroom",
    "entry",
    "office",
    "nursery",
    "storage",
]


class RoomRequirement(BaseModel):
    """One typed room requested by the quick-plan composer.

    Areas are hard constraints, not suggestions: accepting an impossible composition and
    silently producing differently-sized rooms would make the range controls misleading.
    """

    kind: RoomKind
    name: str = Field(min_length=1, max_length=200)
    min_area_m2: float = Field(ge=2, le=200)
    max_area_m2: float = Field(ge=2, le=200)

    @model_validator(mode="after")
    def range_is_ordered(self) -> RoomRequirement:
        if self.max_area_m2 < self.min_area_m2:
            raise ValueError("max_area_m2 must be greater than or equal to min_area_m2")
        return self


class PlanWall(BaseModel):
    a: Point
    b: Point
    thickness_mm: float = Field(gt=0, le=2_000)


class PlanOpening(BaseModel):
    wall: int = Field(ge=0)
    offset_mm: float = Field(ge=0)
    width_mm: float = Field(gt=0)
    kind: str = Field(pattern="^(door|window|opening)$")


class PlanRoom(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    outline: list[Point] = Field(min_length=3, max_length=1_024)
    kind: RoomKind | None = None
    requested_area_m2: tuple[float, float] | None = None


class PlanStair(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    role: Literal["up", "down"]
    from_floor: int = Field(ge=0, le=2)
    to_floor: int = Field(ge=1, le=2)
    outline: list[Point] = Field(min_length=4, max_length=4)
    width_mm: float = Field(ge=700, le=2_000)
    run_mm: float = Field(gt=0, le=12_000)
    step_count: int = Field(ge=10, le=30)
    tread_depth_mm: float = Field(ge=200, le=400)
    riser_height_mm: float = Field(ge=120, le=220)
    railing: bool
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class FloorPlan(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    walls: list[PlanWall] = Field(default_factory=list, max_length=1_024)
    openings: list[PlanOpening] = Field(default_factory=list, max_length=1_024)
    rooms: list[PlanRoom] = Field(default_factory=list, max_length=512)
    stairs: list[PlanStair] = Field(default_factory=list, max_length=4)


class BuildingFloorLevel(BaseModel):
    index: int = Field(ge=0, le=2)
    name: str = Field(min_length=1, max_length=80)
    elevation_mm: float = Field(ge=0, le=12_000)
    plan: FloorPlan


class BuildingFloorPlans(BaseModel):
    version_id: str = Field(min_length=1, max_length=64)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    levels: list[BuildingFloorLevel] = Field(min_length=1, max_length=3)


def _walls_from_outline(outline: list[Point], thickness_mm: float) -> list[PlanWall]:
    return [
        PlanWall(a=point, b=outline[(index + 1) % len(outline)], thickness_mm=thickness_mm)
        for index, point in enumerate(outline)
    ]


def floor_plan_from_house_box(request: HouseBoxRequest, *, plan_id: str, name: str) -> FloorPlan:
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


def floor_plans_from_house_box(
    request: HouseBoxRequest, *, project_id: str, version_id: str, name: str
) -> BuildingFloorPlans:
    """Derive one aligned plan per floor, including the trusted stair/shaft footprint."""
    levels: list[BuildingFloorLevel] = []
    stair_outline: list[Point] | None = None
    if request.stair is not None:
        x, y = _stair_origin(request)
        run = float(request.stair.tread_depth_mm) * request.stair.step_count
        stair_outline = [
            (x, y),
            (x + run, y),
            (x + run, y + float(request.stair.width_mm)),
            (x, y + float(request.stair.width_mm)),
        ]
    for floor_index in range(request.floors):
        plan = floor_plan_from_house_box(
            request,
            plan_id=f"project-{project_id}-floor-{floor_index + 1}",
            name=f"{name} · Floor {floor_index + 1}",
        )
        if request.stair is not None and stair_outline is not None:
            rise = float(request.floor_height_mm) / request.stair.step_count
            if floor_index > 0:
                plan.stairs.append(
                    PlanStair(
                        id=f"stair_{floor_index}_{floor_index + 1}_down",
                        role="down",
                        from_floor=floor_index - 1,
                        to_floor=floor_index,
                        outline=stair_outline,
                        width_mm=request.stair.width_mm,
                        run_mm=request.stair.tread_depth_mm * request.stair.step_count,
                        step_count=request.stair.step_count,
                        tread_depth_mm=request.stair.tread_depth_mm,
                        riser_height_mm=rise,
                        railing=request.stair.railing,
                        material_id=request.stair.material_id,
                    )
                )
            if floor_index < request.floors - 1:
                plan.stairs.append(
                    PlanStair(
                        id=f"stair_{floor_index + 1}_{floor_index + 2}_up",
                        role="up",
                        from_floor=floor_index,
                        to_floor=floor_index + 1,
                        outline=stair_outline,
                        width_mm=request.stair.width_mm,
                        run_mm=request.stair.tread_depth_mm * request.stair.step_count,
                        step_count=request.stair.step_count,
                        tread_depth_mm=request.stair.tread_depth_mm,
                        riser_height_mm=rise,
                        railing=request.stair.railing,
                        material_id=request.stair.material_id,
                    )
                )
        levels.append(
            BuildingFloorLevel(
                index=floor_index,
                name=f"{floor_index + 1} этаж",
                elevation_mm=float(request.floor_height_mm) * floor_index,
                plan=plan,
            )
        )
    return BuildingFloorPlans(
        version_id=version_id,
        floor_height_mm=float(request.floor_height_mm),
        levels=levels,
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


_EPSILON = 1e-6
SEAM_DOOR_CLEARANCE_MM = 200.0
Bounds = tuple[float, float, float, float]
LayoutKind = Literal[
    "equal_strips_v1",
    "lt_decomposition_v1",
    "typed_ranges_v1",
    "typed_ranges_lt_v1",
]


@dataclass(frozen=True, slots=True)
class AutoLayoutResult:
    plan: FloorPlan
    kind: LayoutKind
    zone_room_counts: tuple[int, int] | None = None
    seam: tuple[Point, Point] | None = None


@dataclass(frozen=True, slots=True)
class _Decomposition:
    shape: Literal["l_shape", "t_shape"]
    zones: tuple[Bounds, Bounds]
    seam: tuple[Point, Point]
    boundary_split: Point | None = None


@dataclass(frozen=True, slots=True)
class _ZoneLayout:
    rooms: list[PlanRoom]
    partitions: list[PlanWall]
    openings: list[PlanOpening]


def _same_point(a: Point, b: Point) -> bool:
    return math.isclose(a[0], b[0], abs_tol=_EPSILON) and math.isclose(a[1], b[1], abs_tol=_EPSILON)


def _point_on_segment(point: Point, a: Point, b: Point, *, strict: bool = False) -> bool:
    cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0])
    if not math.isclose(cross, 0.0, abs_tol=_EPSILON):
        return False
    within = (
        min(a[0], b[0]) - _EPSILON <= point[0] <= max(a[0], b[0]) + _EPSILON
        and min(a[1], b[1]) - _EPSILON <= point[1] <= max(a[1], b[1]) + _EPSILON
    )
    if not within:
        return False
    return not strict or (not _same_point(point, a) and not _same_point(point, b))


def _signed_area(outline: list[Point]) -> float:
    return (
        sum(
            point[0] * outline[(index + 1) % len(outline)][1]
            - outline[(index + 1) % len(outline)][0] * point[1]
            for index, point in enumerate(outline)
        )
        / 2
    )


def _normalise_outline(points: list[Point]) -> list[Point]:
    outline: list[Point] = []
    for point in points:
        value = (float(point[0]), float(point[1]))
        if not outline or not _same_point(outline[-1], value):
            outline.append(value)
    if len(outline) > 1 and _same_point(outline[0], outline[-1]):
        outline.pop()

    changed = True
    while changed and len(outline) >= 3:
        changed = False
        for index, point in enumerate(outline):
            previous = outline[index - 1]
            following = outline[(index + 1) % len(outline)]
            if _point_on_segment(point, previous, following, strict=True):
                outline.pop(index)
                changed = True
                break
    if len(outline) < 3:
        raise ValueError("automatic room layout requires a non-degenerate footprint")
    return outline


def _axis_aligned(outline: list[Point]) -> bool:
    return all(
        (
            math.isclose(point[0], following[0], abs_tol=_EPSILON)
            or math.isclose(point[1], following[1], abs_tol=_EPSILON)
        )
        and not _same_point(point, following)
        for index, point in enumerate(outline)
        for following in [outline[(index + 1) % len(outline)]]
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    values = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if values[0] * values[1] < -_EPSILON and values[2] * values[3] < -_EPSILON:
        return True
    return any(
        math.isclose(value, 0.0, abs_tol=_EPSILON) and _point_on_segment(point, start, end)
        for value, point, start, end in (
            (values[0], c, a, b),
            (values[1], d, a, b),
            (values[2], a, c, d),
            (values[3], b, c, d),
        )
    )


def _simple_outline(outline: list[Point]) -> bool:
    edge_count = len(outline)
    for first in range(edge_count):
        a = outline[first]
        b = outline[(first + 1) % edge_count]
        for second in range(first + 1, edge_count):
            if second in {first, (first + 1) % edge_count}:
                continue
            if first == 0 and second == edge_count - 1:
                continue
            c = outline[second]
            d = outline[(second + 1) % edge_count]
            if _segments_intersect(a, b, c, d):
                return False
    return True


def _point_in_outline(point: Point, outline: list[Point], *, boundary: bool = False) -> bool:
    if any(
        _point_on_segment(point, vertex, outline[(index + 1) % len(outline)])
        for index, vertex in enumerate(outline)
    ):
        return boundary
    inside = False
    x, y = point
    for index, a in enumerate(outline):
        b = outline[(index + 1) % len(outline)]
        if (a[1] > y) != (b[1] > y):
            crossing_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if crossing_x > x:
                inside = not inside
    return inside


def _outline_from_rooms(plan: FloorPlan) -> list[Point]:
    if not plan.rooms:
        raise ValueError("automatic room layout requires a footprint")
    if len(plan.rooms) == 1:
        return _normalise_outline(plan.rooms[0].outline)

    room_outlines = [_normalise_outline(room.outline) for room in plan.rooms]
    if any(not _axis_aligned(outline) for outline in room_outlines):
        raise ValueError("automatic room layout requires an axis-aligned footprint")
    xs = sorted({point[0] for outline in room_outlines for point in outline})
    ys = sorted({point[1] for outline in room_outlines for point in outline})
    occupied: set[tuple[int, int]] = set()
    for x_index in range(len(xs) - 1):
        for y_index in range(len(ys) - 1):
            centre = ((xs[x_index] + xs[x_index + 1]) / 2, (ys[y_index] + ys[y_index + 1]) / 2)
            if any(_point_in_outline(centre, outline, boundary=True) for outline in room_outlines):
                occupied.add((x_index, y_index))
    if not occupied:
        raise ValueError("automatic room layout requires a footprint")

    edges: list[tuple[Point, Point]] = []
    for x_index, y_index in occupied:
        x0, x1 = xs[x_index], xs[x_index + 1]
        y0, y1 = ys[y_index], ys[y_index + 1]
        if (x_index, y_index - 1) not in occupied:
            edges.append(((x0, y0), (x1, y0)))
        if (x_index + 1, y_index) not in occupied:
            edges.append(((x1, y0), (x1, y1)))
        if (x_index, y_index + 1) not in occupied:
            edges.append(((x1, y1), (x0, y1)))
        if (x_index - 1, y_index) not in occupied:
            edges.append(((x0, y1), (x0, y0)))

    next_point: dict[Point, Point] = {}
    for start, end in edges:
        if start in next_point:
            raise ValueError("automatic room layout requires a single connected footprint")
        next_point[start] = end
    start = min(next_point)
    outline = [start]
    current = start
    while True:
        following = next_point.get(current)
        if following is None:
            raise ValueError("automatic room layout requires a single connected footprint")
        current = following
        if _same_point(current, start):
            break
        if current in outline:
            raise ValueError("automatic room layout requires a single connected footprint")
        outline.append(current)
    if len(outline) != len(next_point):
        raise ValueError("automatic room layout requires a single connected footprint")
    return _normalise_outline(outline)


def _bounds(outline: list[Point]) -> Bounds:
    return (
        min(point[0] for point in outline),
        min(point[1] for point in outline),
        max(point[0] for point in outline),
        max(point[1] for point in outline),
    )


def _rectangle_bounds(outline: list[Point]) -> Bounds:
    rectangle = _bounds(outline)
    min_x, min_y, max_x, max_y = rectangle
    area = abs(_signed_area(outline))
    if (
        len(outline) != 4
        or (max_x - min_x) * (max_y - min_y) <= 0
        or not math.isclose(area, (max_x - min_x) * (max_y - min_y), rel_tol=1e-9, abs_tol=1.0)
    ):
        raise ValueError("the contour does not split into two axis-aligned rectangles")
    return rectangle


def _insert_outline_point(outline: list[Point], point: Point) -> list[Point]:
    if any(_same_point(point, vertex) for vertex in outline):
        return list(outline)
    for index, vertex in enumerate(outline):
        following = outline[(index + 1) % len(outline)]
        if _point_on_segment(point, vertex, following, strict=True):
            return [*outline[: index + 1], point, *outline[index + 1 :]]
    raise ValueError("the proposed seam does not meet the footprint boundary")


def _split_into_rectangles(
    outline: list[Point], seam: tuple[Point, Point]
) -> tuple[Bounds, Bounds]:
    expanded = _insert_outline_point(_insert_outline_point(outline, seam[0]), seam[1])
    indices = [
        next(index for index, point in enumerate(expanded) if _same_point(point, endpoint))
        for endpoint in seam
    ]
    first, second = indices
    if first > second:
        first, second = second, first
    polygon_a = _normalise_outline(expanded[first : second + 1])
    polygon_b = _normalise_outline([*expanded[second:], *expanded[: first + 1]])
    bounds_a = _rectangle_bounds(polygon_a)
    bounds_b = _rectangle_bounds(polygon_b)
    original_area = abs(_signed_area(outline))
    split_area = abs(_signed_area(polygon_a)) + abs(_signed_area(polygon_b))
    if not math.isclose(original_area, split_area, rel_tol=1e-9, abs_tol=1.0):
        raise ValueError("the proposed seam does not cover the footprint exactly")
    return bounds_a, bounds_b


def _ray_boundary_hit(outline: list[Point], origin: Point, direction: Point) -> Point:
    candidates: list[tuple[float, Point]] = []
    for index, a in enumerate(outline):
        b = outline[(index + 1) % len(outline)]
        if not math.isclose(direction[0], 0.0, abs_tol=_EPSILON):
            if not math.isclose(a[0], b[0], abs_tol=_EPSILON):
                continue
            distance = (a[0] - origin[0]) / direction[0]
            point = (a[0], origin[1])
        else:
            if not math.isclose(a[1], b[1], abs_tol=_EPSILON):
                continue
            distance = (a[1] - origin[1]) / direction[1]
            point = (origin[0], a[1])
        if distance > _EPSILON and _point_on_segment(point, a, b):
            candidates.append((distance, point))
    if not candidates:
        raise ValueError("the L-shaped contour has no opposite boundary for its seam")
    return min(candidates, key=lambda item: item[0])[1]


def _classify_outline(outline: list[Point]) -> _Decomposition | None:
    if not _axis_aligned(outline):
        raise ValueError("automatic room layout requires an axis-aligned footprint")
    if not _simple_outline(outline) or math.isclose(_signed_area(outline), 0.0, abs_tol=1.0):
        raise ValueError("automatic room layout requires a simple connected footprint")

    orientation = 1.0 if _signed_area(outline) > 0 else -1.0
    reflex: list[int] = []
    for index, point in enumerate(outline):
        previous = outline[index - 1]
        following = outline[(index + 1) % len(outline)]
        cross = (point[0] - previous[0]) * (following[1] - point[1]) - (point[1] - previous[1]) * (
            following[0] - point[0]
        )
        if cross * orientation < 0:
            reflex.append(index)

    if not reflex:
        _rectangle_bounds(outline)
        return None
    if len(reflex) >= 3:
        raise ValueError(
            "automatic room layout currently supports rectangle, L and T footprints only"
        )
    if len(reflex) == 2:
        a, b = (outline[index] for index in reflex)
        if not (
            math.isclose(a[0], b[0], abs_tol=_EPSILON) or math.isclose(a[1], b[1], abs_tol=_EPSILON)
        ):
            raise ValueError("this contour's reflex corners don't form a single L or T seam")
        seam = (a, b) if a <= b else (b, a)
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if not _point_in_outline(midpoint, outline):
            raise ValueError("this contour's reflex corners don't form a single L or T seam")
        try:
            zones = _split_into_rectangles(outline, seam)
        except ValueError as exc:
            raise ValueError(
                "this contour's reflex corners don't form a single L or T seam"
            ) from exc
        return _Decomposition(shape="t_shape", zones=zones, seam=seam)

    reflex_index = reflex[0]
    corner = outline[reflex_index]
    candidates: list[tuple[float, _Decomposition]] = []
    for neighbour in (outline[reflex_index - 1], outline[(reflex_index + 1) % len(outline)]):
        direction = (corner[0] - neighbour[0], corner[1] - neighbour[1])
        endpoint = _ray_boundary_hit(outline, corner, direction)
        seam = (corner, endpoint)
        midpoint = ((corner[0] + endpoint[0]) / 2, (corner[1] + endpoint[1]) / 2)
        if not _point_in_outline(midpoint, outline):
            continue
        try:
            zones = _split_into_rectangles(outline, seam)
        except ValueError:
            continue
        areas = [(bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) for bounds in zones]
        candidates.append(
            (
                abs(areas[0] - areas[1]),
                _Decomposition(shape="l_shape", zones=zones, seam=seam, boundary_split=endpoint),
            )
        )
    if not candidates:
        raise ValueError("this contour's reflex corners don't form a single L or T seam")
    return min(candidates, key=lambda item: item[0])[1]


def _validate_layout_request(
    *, room_count: int, partition_thickness_mm: float, door_width_mm: float
) -> None:
    if room_count < 2 or room_count > 8:
        raise ValueError("room_count must be between 2 and 8")
    if partition_thickness_mm < 60 or partition_thickness_mm > 300:
        raise ValueError("partition_thickness_mm must be between 60 and 300")
    if door_width_mm < 600 or door_width_mm > 1_800:
        raise ValueError("door_width_mm must be between 600 and 1800")


def _layout_bounds(
    bounds: Bounds,
    *,
    room_count: int,
    room_number_offset: int,
    partition_thickness_mm: float,
    door_width_mm: float,
    room_requirements: list[RoomRequirement] | None = None,
) -> _ZoneLayout:
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    depth = max_y - min_y
    split_x = width >= depth
    split_span = width if split_x else depth
    partition_length = depth if split_x else width
    if room_requirements is not None and len(room_requirements) != room_count:
        raise ValueError("room requirements do not match the requested room count")
    if split_span / room_count < 2_000 and room_requirements is None:
        raise ValueError("the footprint is too small for that many rooms of at least 2000 mm")
    if room_count > 1 and partition_length < door_width_mm + 400:
        raise ValueError("the partition is too short for the requested door width")

    rooms: list[PlanRoom] = []
    partitions: list[PlanWall] = []
    openings: list[PlanOpening] = []
    if room_requirements is None:
        spans = [split_span / room_count] * room_count
    else:
        total_area_m2 = width * depth / 1_000_000
        minimum = sum(item.min_area_m2 for item in room_requirements)
        maximum = sum(item.max_area_m2 for item in room_requirements)
        if total_area_m2 < minimum - 1e-6 or total_area_m2 > maximum + 1e-6:
            raise ValueError("the footprint area is outside the combined requested room ranges")
        areas = [item.min_area_m2 for item in room_requirements]
        remaining = total_area_m2 - minimum
        headroom = [item.max_area_m2 - item.min_area_m2 for item in room_requirements]
        while remaining > 1e-7:
            available = sum(headroom)
            if available <= 1e-9:
                raise ValueError("the requested room ranges cannot cover the footprint")
            used = 0.0
            for index, room_headroom in enumerate(headroom):
                if room_headroom <= 0:
                    continue
                addition = min(room_headroom, remaining * room_headroom / available)
                areas[index] += addition
                headroom[index] -= addition
                used += addition
            if used <= 1e-9:
                raise ValueError("the requested room ranges cannot cover the footprint")
            remaining -= used
        partition_length_m = partition_length / 1_000
        spans = [area / partition_length_m * 1_000 for area in areas]
        if any(span < 2_000 - _EPSILON for span in spans):
            raise ValueError("a requested room would be narrower than 2000 mm in this footprint")

    cursor = min_x if split_x else min_y
    for index in range(room_count):
        low = cursor
        high = (max_x if split_x else max_y) if index == room_count - 1 else low + spans[index]
        cursor = high
        if split_x:
            outline = [(low, min_y), (high, min_y), (high, max_y), (low, max_y)]
        else:
            outline = [(min_x, low), (max_x, low), (max_x, high), (min_x, high)]
        requirement = room_requirements[index] if room_requirements is not None else None
        rooms.append(
            PlanRoom(
                name=(
                    requirement.name if requirement else f"Room {room_number_offset + index + 1}"
                ),
                outline=outline,
                kind=requirement.kind if requirement else None,
                requested_area_m2=(
                    (requirement.min_area_m2, requirement.max_area_m2) if requirement else None
                ),
            )
        )
        if index == room_count - 1:
            continue
        cut = high
        wall = (
            PlanWall(a=(cut, min_y), b=(cut, max_y), thickness_mm=partition_thickness_mm)
            if split_x
            else PlanWall(a=(min_x, cut), b=(max_x, cut), thickness_mm=partition_thickness_mm)
        )
        partitions.append(wall)
        openings.append(
            PlanOpening(
                wall=len(partitions) - 1,
                offset_mm=(partition_length - door_width_mm) / 2,
                width_mm=door_width_mm,
                kind="door",
            )
        )
    return _ZoneLayout(rooms=rooms, partitions=partitions, openings=openings)


def _seam_partition_offset(seam: tuple[Point, Point], partition: PlanWall) -> float | None:
    """Return the partition crossing offset along an axis-aligned seam, if any."""
    start, end = seam
    seam_horizontal = math.isclose(start[1], end[1], abs_tol=_EPSILON)
    seam_vertical = math.isclose(start[0], end[0], abs_tol=_EPSILON)
    partition_horizontal = math.isclose(partition.a[1], partition.b[1], abs_tol=_EPSILON)
    partition_vertical = math.isclose(partition.a[0], partition.b[0], abs_tol=_EPSILON)

    crossing: Point | None = None
    if seam_horizontal and partition_vertical:
        crossing = (partition.a[0], start[1])
    elif seam_vertical and partition_horizontal:
        crossing = (start[0], partition.a[1])
    elif not seam_horizontal and not seam_vertical:
        raise ValueError("the layout seam must be axis-aligned")
    elif not partition_horizontal and not partition_vertical:
        raise ValueError("layout partitions must be axis-aligned")

    if crossing is None or not (
        _point_on_segment(crossing, start, end)
        and _point_on_segment(crossing, partition.a, partition.b)
    ):
        return None
    return math.hypot(crossing[0] - start[0], crossing[1] - start[1])


def _collision_free_seam_door_offset(
    seam: tuple[Point, Point],
    partitions: list[PlanWall],
    *,
    partition_thickness_mm: float,
    door_width_mm: float,
) -> float:
    """Pick the valid seam-door span nearest the seam centre, deterministically."""
    seam_length = math.hypot(seam[1][0] - seam[0][0], seam[1][1] - seam[0][1])
    intervals = [(SEAM_DOOR_CLEARANCE_MM, seam_length - SEAM_DOOR_CLEARANCE_MM)]
    exclusion_radius = partition_thickness_mm / 2 + SEAM_DOOR_CLEARANCE_MM
    crossings: list[float] = []
    for partition in partitions:
        offset = _seam_partition_offset(seam, partition)
        if offset is not None and not any(
            math.isclose(offset, existing, abs_tol=_EPSILON) for existing in crossings
        ):
            crossings.append(offset)

    for crossing in sorted(crossings):
        exclusion_start = crossing - exclusion_radius
        exclusion_end = crossing + exclusion_radius
        remaining: list[tuple[float, float]] = []
        for interval_start, interval_end in intervals:
            if exclusion_end <= interval_start or exclusion_start >= interval_end:
                remaining.append((interval_start, interval_end))
                continue
            if exclusion_start > interval_start:
                remaining.append((interval_start, min(exclusion_start, interval_end)))
            if exclusion_end < interval_end:
                remaining.append((max(exclusion_end, interval_start), interval_end))
        intervals = remaining

    centred_start = (seam_length - door_width_mm) / 2
    candidates: list[tuple[float, float]] = []
    for interval_start, interval_end in intervals:
        if interval_end - interval_start + _EPSILON < door_width_mm:
            continue
        candidate_start = min(
            max(centred_start, interval_start),
            interval_end - door_width_mm,
        )
        centre_distance = abs(candidate_start + door_width_mm / 2 - seam_length / 2)
        candidates.append((centre_distance, candidate_start))
    if not candidates:
        raise ValueError("the seam has no collision-free span for the requested door width")
    closest_distance = min(candidate[0] for candidate in candidates)
    return min(
        candidate_start
        for centre_distance, candidate_start in candidates
        if math.isclose(centre_distance, closest_distance, abs_tol=_EPSILON)
    )


def _wall_on_boundary(wall: PlanWall, outline: list[Point]) -> bool:
    return any(
        _point_on_segment(wall.a, point, outline[(index + 1) % len(outline)])
        and _point_on_segment(wall.b, point, outline[(index + 1) % len(outline)])
        for index, point in enumerate(outline)
    )


def _exterior_walls_and_openings(
    plan: FloorPlan, outline: list[Point], *, split_point: Point | None
) -> tuple[list[PlanWall], list[PlanOpening]]:
    exterior: list[PlanWall] = []
    remap: dict[int, tuple[int, int | None, float | None]] = {}
    for old_index, wall in enumerate(plan.walls):
        if not _wall_on_boundary(wall, outline):
            continue
        if split_point is not None and _point_on_segment(split_point, wall.a, wall.b, strict=True):
            first = len(exterior)
            exterior.extend(
                [
                    wall.model_copy(update={"b": split_point}),
                    wall.model_copy(update={"a": split_point}),
                ]
            )
            split_offset = math.hypot(split_point[0] - wall.a[0], split_point[1] - wall.a[1])
            remap[old_index] = (first, first + 1, split_offset)
        else:
            remap[old_index] = (len(exterior), None, None)
            exterior.append(wall)
    if not exterior:
        raise ValueError("the footprint boundary is missing exterior walls")
    for index, start in enumerate(outline):
        end = outline[(index + 1) % len(outline)]
        edge_length = math.hypot(end[0] - start[0], end[1] - start[1])
        covered_length = sum(
            math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1])
            for wall in exterior
            if _point_on_segment(wall.a, start, end) and _point_on_segment(wall.b, start, end)
        )
        if not math.isclose(covered_length, edge_length, rel_tol=1e-9, abs_tol=1.0):
            raise ValueError("the footprint boundary is missing exterior walls")

    openings: list[PlanOpening] = []
    for opening in plan.openings:
        mapping = remap.get(opening.wall)
        if mapping is None:
            continue
        new_first, new_second, opening_split_offset = mapping
        if new_second is None or opening_split_offset is None:
            openings.append(opening.model_copy(update={"wall": new_first}))
            continue
        opening_end = opening.offset_mm + opening.width_mm
        if opening_end <= opening_split_offset + _EPSILON:
            openings.append(opening.model_copy(update={"wall": new_first}))
        elif opening.offset_mm >= opening_split_offset - _EPSILON:
            openings.append(
                opening.model_copy(
                    update={
                        "wall": new_second,
                        "offset_mm": opening.offset_mm - opening_split_offset,
                    }
                )
            )
        else:
            raise ValueError("an exterior opening crosses the L-shaped layout seam")
    return exterior, openings


def _rectangular_bounds(plan: FloorPlan) -> Bounds:
    outline = _outline_from_rooms(plan)
    try:
        return _rectangle_bounds(outline)
    except ValueError as exc:
        raise ValueError(
            "automatic room layout currently requires an axis-aligned rectangle"
        ) from exc


def auto_layout_rectangular_plan(
    plan: FloorPlan,
    *,
    room_count: int,
    partition_thickness_mm: float = 120.0,
    door_width_mm: float = 900.0,
    room_requirements: list[RoomRequirement] | None = None,
) -> FloorPlan:
    """Split a rectangular footprint into connected rooms with one door per partition.

    Kept as the stable rectangle-only entry point while ``auto_layout_plan`` dispatches
    rectangle, L and T footprints through the same strip cutter.
    """
    _validate_layout_request(
        room_count=room_count,
        partition_thickness_mm=partition_thickness_mm,
        door_width_mm=door_width_mm,
    )
    if plan.stairs:
        raise ValueError("automatic room layout does not yet support floors with a stair opening")

    min_x, min_y, max_x, max_y = _rectangular_bounds(plan)

    def exterior(wall: PlanWall) -> bool:
        if math.isclose(wall.a[0], wall.b[0], abs_tol=_EPSILON):
            return math.isclose(wall.a[0], min_x, abs_tol=_EPSILON) or math.isclose(
                wall.a[0], max_x, abs_tol=_EPSILON
            )
        if math.isclose(wall.a[1], wall.b[1], abs_tol=_EPSILON):
            return math.isclose(wall.a[1], min_y, abs_tol=_EPSILON) or math.isclose(
                wall.a[1], max_y, abs_tol=_EPSILON
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
    layout = _layout_bounds(
        (min_x, min_y, max_x, max_y),
        room_count=room_count,
        room_number_offset=0,
        partition_thickness_mm=partition_thickness_mm,
        door_width_mm=door_width_mm,
        room_requirements=room_requirements,
    )
    openings.extend(
        opening.model_copy(update={"wall": len(outer_walls) + opening.wall})
        for opening in layout.openings
    )

    return plan.model_copy(
        update={
            "walls": [*outer_walls, *layout.partitions],
            "openings": openings,
            "rooms": layout.rooms,
        }
    )


def auto_layout_plan(
    plan: FloorPlan,
    *,
    room_count: int,
    partition_thickness_mm: float = 120.0,
    door_width_mm: float = 900.0,
    room_requirements: list[RoomRequirement] | None = None,
) -> AutoLayoutResult:
    """Lay out a rectangle, L or T footprint and reject every other contour."""
    _validate_layout_request(
        room_count=room_count,
        partition_thickness_mm=partition_thickness_mm,
        door_width_mm=door_width_mm,
    )
    if room_requirements is not None and len(room_requirements) != room_count:
        raise ValueError("room requirements do not match the requested room count")
    if plan.stairs:
        raise ValueError("automatic room layout does not yet support floors with a stair opening")
    outline = _outline_from_rooms(plan)
    decomposition = _classify_outline(outline)
    if decomposition is None:
        return AutoLayoutResult(
            plan=auto_layout_rectangular_plan(
                plan,
                room_count=room_count,
                partition_thickness_mm=partition_thickness_mm,
                door_width_mm=door_width_mm,
                room_requirements=room_requirements,
            ),
            kind="typed_ranges_v1" if room_requirements is not None else "equal_strips_v1",
        )

    seam_length = math.hypot(
        decomposition.seam[1][0] - decomposition.seam[0][0],
        decomposition.seam[1][1] - decomposition.seam[0][1],
    )
    if seam_length < door_width_mm + 400:
        raise ValueError(
            "the seam between the two parts of the house is too short for the requested door width"
        )
    areas = [(bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) for bounds in decomposition.zones]
    zone_requirements: tuple[list[RoomRequirement] | None, list[RoomRequirement] | None]
    typed_zone_layouts: tuple[_ZoneLayout, _ZoneLayout] | None = None
    if room_requirements is None:
        room_count_a = max(1, round(room_count * areas[0] / sum(areas)))
        room_count_b = room_count - room_count_a
        if room_count_b < 1:
            room_count_a -= 1
            room_count_b = 1
        zone_requirements = (None, None)
    else:
        candidates: list[
            tuple[
                float,
                int,
                list[RoomRequirement],
                list[RoomRequirement],
                _ZoneLayout,
                _ZoneLayout,
            ]
        ] = []
        area_m2 = [value / 1_000_000 for value in areas]
        for mask in range(1, (1 << room_count) - 1):
            left = [item for index, item in enumerate(room_requirements) if mask & (1 << index)]
            right = [
                item for index, item in enumerate(room_requirements) if not mask & (1 << index)
            ]
            if not (
                sum(item.min_area_m2 for item in left) - 1e-6
                <= area_m2[0]
                <= sum(item.max_area_m2 for item in left) + 1e-6
                and sum(item.min_area_m2 for item in right) - 1e-6
                <= area_m2[1]
                <= sum(item.max_area_m2 for item in right) + 1e-6
            ):
                continue
            target_left = sum((item.min_area_m2 + item.max_area_m2) / 2 for item in left)
            target_right = sum((item.min_area_m2 + item.max_area_m2) / 2 for item in right)
            score = abs(target_left - area_m2[0]) + abs(target_right - area_m2[1])
            try:
                left_layout = _layout_bounds(
                    decomposition.zones[0],
                    room_count=len(left),
                    room_number_offset=0,
                    partition_thickness_mm=partition_thickness_mm,
                    door_width_mm=door_width_mm,
                    room_requirements=left,
                )
                right_layout = _layout_bounds(
                    decomposition.zones[1],
                    room_count=len(right),
                    room_number_offset=len(left),
                    partition_thickness_mm=partition_thickness_mm,
                    door_width_mm=door_width_mm,
                    room_requirements=right,
                )
            except ValueError:
                continue
            candidates.append((score, mask, left, right, left_layout, right_layout))
        if not candidates:
            raise ValueError(
                "the requested room ranges cannot be assigned to both parts of this footprint"
            )
        _, _, left, right, left_layout, right_layout = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        room_count_a, room_count_b = len(left), len(right)
        zone_requirements = (left, right)
        typed_zone_layouts = (left_layout, right_layout)

    exterior, openings = _exterior_walls_and_openings(
        plan, outline, split_point=decomposition.boundary_split
    )
    if typed_zone_layouts is not None:
        zone_a, zone_b = typed_zone_layouts
    else:
        zone_a = _layout_bounds(
            decomposition.zones[0],
            room_count=room_count_a,
            room_number_offset=0,
            partition_thickness_mm=partition_thickness_mm,
            door_width_mm=door_width_mm,
            room_requirements=zone_requirements[0],
        )
        zone_b = _layout_bounds(
            decomposition.zones[1],
            room_count=room_count_b,
            room_number_offset=room_count_a,
            partition_thickness_mm=partition_thickness_mm,
            door_width_mm=door_width_mm,
            room_requirements=zone_requirements[1],
        )
    partitions = [*zone_a.partitions, *zone_b.partitions]
    openings.extend(
        opening.model_copy(update={"wall": len(exterior) + opening.wall})
        for opening in zone_a.openings
    )
    openings.extend(
        opening.model_copy(
            update={
                "wall": len(exterior) + len(zone_a.partitions) + opening.wall,
            }
        )
        for opening in zone_b.openings
    )
    seam_wall_index = len(exterior) + len(partitions)
    seam_wall = PlanWall(
        a=decomposition.seam[0],
        b=decomposition.seam[1],
        thickness_mm=partition_thickness_mm,
    )
    seam_door_offset = _collision_free_seam_door_offset(
        decomposition.seam,
        partitions,
        partition_thickness_mm=partition_thickness_mm,
        door_width_mm=door_width_mm,
    )
    openings.append(
        PlanOpening(
            wall=seam_wall_index,
            offset_mm=seam_door_offset,
            width_mm=door_width_mm,
            kind="door",
        )
    )
    laid_out = plan.model_copy(
        update={
            "walls": [*exterior, *partitions, seam_wall],
            "openings": openings,
            "rooms": [*zone_a.rooms, *zone_b.rooms],
        }
    )
    return AutoLayoutResult(
        plan=laid_out,
        kind=("typed_ranges_lt_v1" if room_requirements is not None else "lt_decomposition_v1"),
        zone_room_counts=(room_count_a, room_count_b),
        seam=decomposition.seam,
    )
