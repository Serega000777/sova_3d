"""Convert Apple RoomPlan's metric wall surfaces into the shared 2D floor-plan model.

The native bridge sends only the small, stable subset needed for a plan: wall endpoints,
height, and opening centres/widths in metres.  The server validates and snaps that measured
geometry before it is allowed into immutable project provenance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engineering.floor_plan import (
    BuildingFloorLevel,
    FloorPlan,
    PlanOpening,
    PlanRoom,
    PlanWall,
)

PointM = tuple[float, float]
PointMM = tuple[float, float]

MAX_SURFACES = 512
MIN_WALL_LENGTH_M = 0.25
MAX_WALL_LENGTH_M = 100.0
MAX_ROOM_PERIMETER_M = 500.0
SNAP_TOLERANCE_MM = 750.0
DEFAULT_WALL_THICKNESS_MM = 120.0
MAX_STRUCTURE_FLOORS = 3
SAME_FLOOR_TOLERANCE_M = 0.25
MIN_FLOOR_GAP_M = 1.5
MAX_FLOOR_GAP_M = 6.0


class RoomPlanWallSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=100)
    a_m: PointM
    b_m: PointM
    height_m: float = Field(gt=0.2, le=20)
    transform_m: tuple[float, ...] | None = None
    dimensions_m: tuple[float, float, float] | None = None


class RoomPlanOpeningSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=100)
    parent_wall_id: str | None = Field(default=None, max_length=100)
    center_m: PointM
    width_m: float = Field(gt=0.1, le=20)
    kind: Literal["door", "window", "opening"]
    transform_m: tuple[float, ...] | None = None
    dimensions_m: tuple[float, float, float] | None = None


class RoomPlanCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
    room_id: str = Field(min_length=1, max_length=100)
    floor_elevation_m: float | None = Field(default=None, ge=-100, le=100)
    walls: list[RoomPlanWallSurface] = Field(min_length=3, max_length=MAX_SURFACES)
    openings: list[RoomPlanOpeningSurface] = Field(default_factory=list, max_length=MAX_SURFACES)

    @model_validator(mode="after")
    def complete_v2_geometry(self) -> RoomPlanCapture:
        if self.schema_version == 1:
            return self
        surfaces: list[RoomPlanWallSurface | RoomPlanOpeningSurface] = [
            *self.walls,
            *self.openings,
        ]
        for surface in surfaces:
            if surface.transform_m is None or len(surface.transform_m) != 16:
                raise ValueError(f"RoomPlan v2 surface {surface.identifier} needs a 4x4 transform")
            if not all(math.isfinite(value) for value in surface.transform_m):
                raise ValueError(f"RoomPlan surface {surface.identifier} transform must be finite")
            if (
                any(abs(surface.transform_m[index]) > 1e-5 for index in (3, 7, 11))
                or abs(surface.transform_m[15] - 1) > 1e-5
            ):
                raise ValueError(f"RoomPlan surface {surface.identifier} transform must be affine")
            basis = [
                surface.transform_m[0:3],
                surface.transform_m[4:7],
                surface.transform_m[8:11],
            ]
            lengths = [
                math.sqrt(sum(component * component for component in axis)) for axis in basis
            ]
            if any(not 0.9 <= length <= 1.1 for length in lengths) or any(
                abs(sum(left[k] * right[k] for k in range(3))) > 0.1
                for index, left in enumerate(basis)
                for right in basis[index + 1 :]
            ):
                raise ValueError(
                    f"RoomPlan surface {surface.identifier} transform basis must be orthonormal"
                )
            dimensions = surface.dimensions_m
            if dimensions is None or not all(
                math.isfinite(value) and value > 0 for value in dimensions
            ):
                raise ValueError(
                    f"RoomPlan v2 surface {surface.identifier} needs positive dimensions"
                )
        return self


def _floor_elevation(room: RoomPlanCapture) -> float:
    if room.floor_elevation_m is None:
        raise ValueError("RoomPlan structure requires each room's floor elevation")
    return float(room.floor_elevation_m)


def _structure_floor_groups(rooms: list[RoomPlanCapture]) -> list[list[int]]:
    """Cluster measured floor elevations while keeping scan drift inside one level."""
    ordered = sorted((_floor_elevation(room), index) for index, room in enumerate(rooms))
    groups: list[list[int]] = []
    elevations: list[list[float]] = []
    for elevation, index in ordered:
        if not groups or elevation - min(elevations[-1]) > SAME_FLOOR_TOLERANCE_M:
            groups.append([index])
            elevations.append([elevation])
        else:
            groups[-1].append(index)
            elevations[-1].append(elevation)
    if len(groups) > MAX_STRUCTURE_FLOORS:
        raise ValueError("RoomPlan structure supports at most three measured floor levels")
    floor_elevations = [float(median(values)) for values in elevations]
    for lower, upper in zip(floor_elevations, floor_elevations[1:], strict=False):
        gap = upper - lower
        if not MIN_FLOOR_GAP_M <= gap <= MAX_FLOOR_GAP_M:
            raise ValueError("RoomPlan structure floor levels must be separated by 1.5 to 6 metres")
    if floor_elevations and floor_elevations[-1] - floor_elevations[0] > 12:
        raise ValueError("RoomPlan structure floor elevations exceed the 12 metre limit")
    return groups


class RoomPlanStructureCapture(BaseModel):
    """Several RoomPlan rooms that Apple merged in one continuous ARKit world frame."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    structure_id: str = Field(min_length=1, max_length=100)
    coordinate_space: Literal["shared_arkit_world"]
    rooms: list[RoomPlanCapture] = Field(min_length=2, max_length=64)

    @model_validator(mode="after")
    def shared_frame_is_bounded(self) -> RoomPlanStructureCapture:
        room_ids = [room.room_id for room in self.rooms]
        if len(set(room_ids)) != len(room_ids):
            raise ValueError("RoomPlan structure room identifiers must be unique")
        if any(room.schema_version != 2 for room in self.rooms):
            raise ValueError("RoomPlan structure requires complete v2 room geometry")
        floor_elevations = [room.floor_elevation_m for room in self.rooms]
        if any(elevation is None or not math.isfinite(elevation) for elevation in floor_elevations):
            raise ValueError("RoomPlan structure requires each room's floor elevation")
        for room in self.rooms:
            measured_floor = float(
                median(
                    float(wall.transform_m[13]) - float(wall.dimensions_m[1]) / 2
                    for wall in room.walls
                    if wall.transform_m is not None and wall.dimensions_m is not None
                )
            )
            if abs(_floor_elevation(room) - measured_floor) > 0.1:
                raise ValueError(
                    "RoomPlan structure floor elevation disagrees with measured wall transforms"
                )
        _structure_floor_groups(self.rooms)
        if sum(len(room.walls) + len(room.openings) for room in self.rooms) > 1_024:
            raise ValueError("RoomPlan structure exceeds the 1024 surface limit")
        return self


@dataclass(frozen=True, slots=True)
class RoomPlanConversion:
    plan: FloorPlan
    floor_height_mm: float
    warnings: tuple[str, ...]
    wall_ids: tuple[str, ...]
    source_origin_mm: PointMM
    opening_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoomPlanStructureConversion:
    plan: FloorPlan
    levels: tuple[BuildingFloorLevel, ...]
    floor_height_mm: float
    warnings: tuple[str, ...]
    room_ids: tuple[str, ...]
    source_origin_mm: PointMM


def _distance(a: PointMM, b: PointMM) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(a: PointMM, b: PointMM, c: PointMM) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _proper_intersection(a: PointMM, b: PointMM, c: PointMM, d: PointMM) -> bool:
    """Whether two non-adjacent segments cross away from their endpoints."""
    return (_cross(a, b, c) * _cross(a, b, d) < 0) and (_cross(c, d, a) * _cross(c, d, b) < 0)


def _as_mm(point: PointM) -> PointMM:
    values = (float(point[0]) * 1_000, float(point[1]) * 1_000)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("RoomPlan coordinates must be finite")
    return values


def _ordered_segments(
    walls: list[RoomPlanWallSurface],
) -> list[tuple[str, PointMM, PointMM, float]]:
    """Greedily orient one measured wall loop, tolerating small LiDAR endpoint gaps."""
    segments: list[tuple[str, PointMM, PointMM, float]] = []
    perimeter = 0.0
    identifiers: set[str] = set()
    for wall in walls:
        if wall.identifier in identifiers:
            raise ValueError("RoomPlan wall identifiers must be unique")
        identifiers.add(wall.identifier)
        a, b = _as_mm(wall.a_m), _as_mm(wall.b_m)
        length = _distance(a, b)
        if length < MIN_WALL_LENGTH_M * 1_000 or length > MAX_WALL_LENGTH_M * 1_000:
            raise ValueError(
                f"RoomPlan wall {wall.identifier} length must be between "
                f"{MIN_WALL_LENGTH_M:g} and {MAX_WALL_LENGTH_M:g} metres"
            )
        perimeter += length
        segments.append((wall.identifier, a, b, float(wall.height_m) * 1_000))
    if perimeter > MAX_ROOM_PERIMETER_M * 1_000:
        raise ValueError("RoomPlan room perimeter exceeds the 500 metre limit")

    ordered = [segments.pop(0)]
    while segments:
        current = ordered[-1][2]
        candidates: list[tuple[float, int, bool]] = []
        for index, (_, a, b, _) in enumerate(segments):
            candidates.append((_distance(current, a), index, False))
            candidates.append((_distance(current, b), index, True))
        gap, index, reverse = min(candidates, key=lambda item: item[0])
        if gap > SNAP_TOLERANCE_MM:
            raise ValueError("RoomPlan walls do not form one connected room perimeter")
        identifier, a, b, height = segments.pop(index)
        ordered.append((identifier, b, a, height) if reverse else (identifier, a, b, height))
    if _distance(ordered[-1][2], ordered[0][1]) > SNAP_TOLERANCE_MM:
        raise ValueError("RoomPlan walls do not close into a room perimeter")
    return ordered


def _snapped_walls(
    ordered: list[tuple[str, PointMM, PointMM, float]],
) -> tuple[list[PlanWall], list[PointMM], dict[str, int], PointMM]:
    # Each corner is the midpoint of the two measured wall ends that should meet there.
    corners = [
        (
            (ordered[index - 1][2][0] + segment[1][0]) / 2,
            (ordered[index - 1][2][1] + segment[1][1]) / 2,
        )
        for index, segment in enumerate(ordered)
    ]
    min_x = min(point[0] for point in corners)
    min_y = min(point[1] for point in corners)
    normalized = [(point[0] - min_x, point[1] - min_y) for point in corners]
    count = len(normalized)
    for first in range(count):
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or first == (second + 1) % count:
                continue
            if _proper_intersection(
                normalized[first],
                normalized[(first + 1) % count],
                normalized[second],
                normalized[(second + 1) % count],
            ):
                raise ValueError("RoomPlan walls form a self-intersecting room outline")
    area = abs(
        sum(
            point[0] * normalized[(index + 1) % count][1]
            - normalized[(index + 1) % count][0] * point[1]
            for index, point in enumerate(normalized)
        )
        / 2
    )
    if area < 250_000:
        raise ValueError("RoomPlan room outline is degenerate or smaller than 0.25 m²")
    plan_walls = [
        PlanWall(
            a=point,
            b=normalized[(index + 1) % len(normalized)],
            thickness_mm=DEFAULT_WALL_THICKNESS_MM,
        )
        for index, point in enumerate(normalized)
    ]
    wall_indices = {segment[0]: index for index, segment in enumerate(ordered)}
    return plan_walls, normalized, wall_indices, (min_x, min_y)


def _opening_wall(
    center: PointMM,
    parent_wall_id: str | None,
    walls: list[PlanWall],
    wall_indices: dict[str, int],
) -> tuple[int, float] | None:
    if parent_wall_id in wall_indices:
        index = wall_indices[parent_wall_id]
        wall = walls[index]
        length = _distance(wall.a, wall.b)
        ux, uy = (wall.b[0] - wall.a[0]) / length, (wall.b[1] - wall.a[1]) / length
        projection = (center[0] - wall.a[0]) * ux + (center[1] - wall.a[1]) * uy
        point = (wall.a[0] + ux * projection, wall.a[1] + uy * projection)
        if (
            _distance(center, point) > SNAP_TOLERANCE_MM
            or projection < -SNAP_TOLERANCE_MM
            or projection > length + SNAP_TOLERANCE_MM
        ):
            return None
        return index, projection

    # Older RoomPlan results may omit parentIdentifier.  Associate only when the nearest
    # measured wall is unambiguous and within the same conservative LiDAR snap tolerance.
    candidates: list[tuple[float, int, float]] = []
    for index, wall in enumerate(walls):
        length = _distance(wall.a, wall.b)
        ux, uy = (wall.b[0] - wall.a[0]) / length, (wall.b[1] - wall.a[1]) / length
        projection = (center[0] - wall.a[0]) * ux + (center[1] - wall.a[1]) * uy
        closest = max(0.0, min(length, projection))
        point = (wall.a[0] + ux * closest, wall.a[1] + uy * closest)
        candidates.append((_distance(center, point), index, projection))
    distance, index, projection = min(candidates, key=lambda item: item[0])
    return (index, projection) if distance <= SNAP_TOLERANCE_MM else None


def floor_plan_from_room_plan(
    capture: RoomPlanCapture, *, plan_id: str, name: str
) -> RoomPlanConversion:
    """Validate, snap and normalize one metric RoomPlan room into millimetres."""
    ordered = _ordered_segments(capture.walls)
    walls, outline, wall_indices, origin = _snapped_walls(ordered)
    openings: list[PlanOpening] = []
    opening_ids: list[str] = []
    warnings: list[str] = []

    for opening in capture.openings:
        source_center = _as_mm(opening.center_m)
        center = (source_center[0] - origin[0], source_center[1] - origin[1])
        matched = _opening_wall(center, opening.parent_wall_id, walls, wall_indices)
        if matched is None:
            warnings.append(f"opening {opening.identifier} could not be matched to a wall")
            continue
        wall_index, center_offset = matched
        length = _distance(walls[wall_index].a, walls[wall_index].b)
        width = float(opening.width_m) * 1_000
        if width >= length:
            warnings.append(f"opening {opening.identifier} is wider than its wall")
            continue
        height = (
            float(opening.dimensions_m[1]) * 1_000
            if opening.dimensions_m is not None
            and math.isfinite(opening.dimensions_m[1])
            and opening.dimensions_m[1] > 0
            else None
        )
        wall_height = ordered[wall_index][3]
        if height is not None and height > wall_height:
            warnings.append(f"opening {opening.identifier} is taller than its wall")
        offset = max(0.0, min(length - width, center_offset - width / 2))
        openings.append(
            PlanOpening(
                wall=wall_index,
                offset_mm=offset,
                width_mm=width,
                height_mm=height,
                kind=opening.kind,
            )
        )
        opening_ids.append(opening.identifier)

    heights = [height for _, _, _, height in ordered]
    return RoomPlanConversion(
        plan=FloorPlan(
            id=plan_id,
            name=name,
            walls=walls,
            openings=openings,
            rooms=[PlanRoom(name=name, outline=outline)],
        ),
        floor_height_mm=float(median(heights)),
        warnings=tuple(warnings),
        wall_ids=tuple(identifier for identifier, _, _, _ in ordered),
        source_origin_mm=origin,
        opening_ids=tuple(opening_ids),
    )


def _translated(point: PointMM, offset: PointMM) -> PointMM:
    return (point[0] + offset[0], point[1] + offset[1])


def _point_strictly_inside_polygon(point: PointMM, polygon: list[PointMM]) -> bool:
    """Odd-even containment that treats a shared boundary as outside."""
    inside = False
    x, y = point
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        cross = _cross(a, b, point)
        if (
            abs(cross) <= 1e-6
            and min(a[0], b[0]) <= x <= max(a[0], b[0])
            and min(a[1], b[1]) <= y <= max(a[1], b[1])
        ):
            return False
        if (a[1] > y) != (b[1] > y):
            intersection_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if intersection_x > x:
                inside = not inside
    return inside


def _outlines_overlap(left: list[PointMM], right: list[PointMM]) -> bool:
    for left_index, left_a in enumerate(left):
        left_b = left[(left_index + 1) % len(left)]
        for right_index, right_a in enumerate(right):
            right_b = right[(right_index + 1) % len(right)]
            if _proper_intersection(left_a, left_b, right_a, right_b):
                return True
    left_probes = [
        *left,
        *[
            (
                (point[0] + left[(index + 1) % len(left)][0]) / 2,
                (point[1] + left[(index + 1) % len(left)][1]) / 2,
            )
            for index, point in enumerate(left)
        ],
        (sum(point[0] for point in left) / len(left), sum(point[1] for point in left) / len(left)),
    ]
    right_probes = [
        *right,
        *[
            (
                (point[0] + right[(index + 1) % len(right)][0]) / 2,
                (point[1] + right[(index + 1) % len(right)][1]) / 2,
            )
            for index, point in enumerate(right)
        ],
        (
            sum(point[0] for point in right) / len(right),
            sum(point[1] for point in right) / len(right),
        ),
    ]
    return any(_point_strictly_inside_polygon(point, right) for point in left_probes) or any(
        _point_strictly_inside_polygon(point, left) for point in right_probes
    )


def floor_plan_from_room_plan_structure(
    capture: RoomPlanStructureCapture, *, plan_id: str, name: str
) -> RoomPlanStructureConversion:
    """Preserve Apple's shared world frame in one aligned plan per measured floor."""
    converted = [
        floor_plan_from_room_plan(
            room,
            plan_id=f"{plan_id}-room-{index + 1}",
            name=f"Комната {index + 1}",
        )
        for index, room in enumerate(capture.rooms)
    ]
    global_origin = (
        min(room.source_origin_mm[0] for room in converted),
        min(room.source_origin_mm[1] for room in converted),
    )
    floor_groups = _structure_floor_groups(capture.rooms)
    warnings: list[str] = []
    floor_elevations = [
        float(median(_floor_elevation(capture.rooms[index]) for index in group))
        for group in floor_groups
    ]
    base_elevation = floor_elevations[0]
    levels: list[BuildingFloorLevel] = []
    all_points: list[PointMM] = []
    for floor_index, room_indices in enumerate(floor_groups):
        walls: list[PlanWall] = []
        openings: list[PlanOpening] = []
        rooms: list[PlanRoom] = []
        outlines: list[list[PointMM]] = []
        for room_index in room_indices:
            room = converted[room_index]
            offset = (
                room.source_origin_mm[0] - global_origin[0],
                room.source_origin_mm[1] - global_origin[1],
            )
            wall_offset = len(walls)
            walls.extend(
                PlanWall(
                    a=_translated(wall.a, offset),
                    b=_translated(wall.b, offset),
                    thickness_mm=wall.thickness_mm,
                    height_mm=wall.height_mm,
                    material_id=wall.material_id,
                )
                for wall in room.plan.walls
            )
            openings.extend(
                opening.model_copy(update={"wall": opening.wall + wall_offset})
                for opening in room.plan.openings
            )
            outline = [_translated(point, offset) for point in room.plan.rooms[0].outline]
            if any(_outlines_overlap(outline, existing) for existing in outlines):
                raise ValueError(
                    "RoomPlan structure rooms overlap on one floor in the shared world frame"
                )
            outlines.append(outline)
            all_points.extend(outline)
            rooms.append(PlanRoom(name=f"Комната {room_index + 1}", outline=outline))
            warnings.extend(
                f"room {capture.rooms[room_index].room_id}: {warning}" for warning in room.warnings
            )
        level_plan = FloorPlan(
            id=plan_id if len(floor_groups) == 1 else f"{plan_id}-floor-{floor_index + 1}",
            name=(name if len(floor_groups) == 1 else f"{name} · {floor_index + 1} этаж"),
            walls=walls,
            openings=openings,
            rooms=rooms,
        )
        levels.append(
            BuildingFloorLevel(
                index=floor_index,
                name=f"{floor_index + 1} этаж",
                elevation_mm=(floor_elevations[floor_index] - base_elevation) * 1_000,
                plan=level_plan,
            )
        )

    if (
        max(point[0] for point in all_points) - min(point[0] for point in all_points) > 500_000
        or max(point[1] for point in all_points) - min(point[1] for point in all_points) > 500_000
    ):
        raise ValueError("RoomPlan structure exceeds the 500 metre shared-frame limit")

    heights = [room.floor_height_mm for room in converted]
    if max(heights) - min(heights) > 500:
        raise ValueError("RoomPlan structure room heights disagree by more than 500 mm")
    floor_height_mm = float(median(heights))
    if len(levels) > 1 and not 2_200 <= floor_height_mm <= 6_000:
        raise ValueError("Multi-floor RoomPlan structure height must be between 2.2 and 6 metres")
    return RoomPlanStructureConversion(
        plan=levels[0].plan,
        levels=tuple(levels),
        floor_height_mm=floor_height_mm,
        warnings=tuple(warnings),
        room_ids=tuple(room.room_id for room in capture.rooms),
        source_origin_mm=global_origin,
    )
