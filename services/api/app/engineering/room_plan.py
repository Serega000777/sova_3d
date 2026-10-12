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

from app.engineering.floor_plan import FloorPlan, PlanOpening, PlanRoom, PlanWall

PointM = tuple[float, float]
PointMM = tuple[float, float]

MAX_SURFACES = 512
MIN_WALL_LENGTH_M = 0.25
MAX_WALL_LENGTH_M = 100.0
MAX_ROOM_PERIMETER_M = 500.0
SNAP_TOLERANCE_MM = 750.0
DEFAULT_WALL_THICKNESS_MM = 120.0


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


@dataclass(frozen=True, slots=True)
class RoomPlanConversion:
    plan: FloorPlan
    floor_height_mm: float
    warnings: tuple[str, ...]
    wall_ids: tuple[str, ...]
    source_origin_mm: PointMM
    opening_ids: tuple[str, ...]


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
        offset = max(0.0, min(length - width, center_offset - width / 2))
        openings.append(
            PlanOpening(
                wall=wall_index,
                offset_mm=offset,
                width_mm=width,
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
