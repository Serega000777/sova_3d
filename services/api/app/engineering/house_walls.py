"""Freeform house walls (T-238): a hand-drawn 2D perimeter extruded into one fused solid.

Mirrors `house_box.py`'s pattern (several `create_box` primitives + sequential `boolean fuse`
into one accumulating body) but takes an arbitrary number of wall segments instead of a fixed
shape, so the segments must each be rotated into place along their own direction first.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Annotated

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass

from app.geometry.operations import OperationPlan

Point = tuple[float, float]

WallThickness = Annotated[float, Field(ge=60, le=600)]
FloorHeight = Annotated[float, Field(ge=2_200, le=6_000)]
FloorCount = Annotated[int, Field(ge=1, le=3)]

MIN_WALLS = 3
MIN_WALL_LENGTH_MM = 2_000.0
MAX_WALL_LENGTH_MM = 50_000.0
# A generous cap on the whole footprint, well above any realistic single-family house, so an
# obviously malformed drawing (e.g. units pasted in the wrong scale) fails fast.
MAX_PERIMETER_MM = 200_000.0
# Endpoints snapped on the drawing canvas land exactly on each other; this only absorbs float
# drift from client-side math, not a real search radius.
ENDPOINT_EPSILON_MM = 1.0


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class PlanWallInput:
    """Mirrors `PlanWall` from `packages/contracts/src/floor-plan.ts`."""

    a: Point
    b: Point
    thickness_mm: WallThickness = 120.0


def _wall_length(wall: PlanWallInput) -> float:
    return math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1])


def _open_endpoints(
    walls: Sequence[PlanWallInput], epsilon_mm: float = ENDPOINT_EPSILON_MM
) -> list[Point]:
    """Wall ends touched by only one wall — the same check as `openWallEndpoints` in contracts."""
    points: list[Point] = []
    degree: list[int] = []

    def find(p: Point) -> int:
        for i, q in enumerate(points):
            if math.hypot(q[0] - p[0], q[1] - p[1]) <= epsilon_mm:
                return i
        points.append(p)
        degree.append(0)
        return len(points) - 1

    for wall in walls:
        degree[find(wall.a)] += 1
        degree[find(wall.b)] += 1
    return [p for p, d in zip(points, degree, strict=True) if d == 1]


def ordered_wall_outline(
    walls: Sequence[PlanWallInput], epsilon_mm: float = ENDPOINT_EPSILON_MM
) -> list[Point]:
    """Return one ordered polygon or reject branches/disconnected closed loops.

    The old dangling-end check accepted two separate triangles because every vertex still
    had degree two.  A house footprint must be one connected cycle: every node has degree
    exactly two and walking the first cycle must consume every wall.
    """
    points: list[Point] = []
    adjacency: list[list[tuple[int, int]]] = []

    def find(point: Point) -> int:
        for index, known in enumerate(points):
            if math.hypot(known[0] - point[0], known[1] - point[1]) <= epsilon_mm:
                return index
        points.append(point)
        adjacency.append([])
        return len(points) - 1

    endpoints: list[tuple[int, int]] = []
    for edge_index, wall in enumerate(walls):
        a = find(wall.a)
        b = find(wall.b)
        endpoints.append((a, b))
        adjacency[a].append((edge_index, b))
        adjacency[b].append((edge_index, a))

    if len(walls) < MIN_WALLS or any(len(edges) != 2 for edges in adjacency):
        raise ValueError("walls do not form a closed perimeter: expected a single connected loop")

    start = endpoints[0][0]
    current = start
    used: set[int] = set()
    outline: list[Point] = []
    while True:
        outline.append(points[current])
        available = [(edge, other) for edge, other in adjacency[current] if edge not in used]
        if not available:
            break
        edge, other = available[0]
        used.add(edge)
        current = other
        if current == start:
            break

    if current != start or len(used) != len(walls) or len(outline) < MIN_WALLS:
        raise ValueError("walls do not form a closed perimeter: expected a single connected loop")
    return outline


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class HouseWallsRequest:
    walls: list[PlanWallInput]
    floor_height_mm: FloorHeight
    floors: FloorCount

    @model_validator(mode="after")
    def _validate_contour(self) -> HouseWallsRequest:
        if len(self.walls) < MIN_WALLS:
            raise ValueError(f"at least {MIN_WALLS} walls are needed to close a perimeter")
        perimeter = 0.0
        for index, wall in enumerate(self.walls):
            length = _wall_length(wall)
            if length < MIN_WALL_LENGTH_MM or length > MAX_WALL_LENGTH_MM:
                raise ValueError(
                    f"wall {index}: length {length:.0f}mm must be between "
                    f"{MIN_WALL_LENGTH_MM:.0f} and {MAX_WALL_LENGTH_MM:.0f}mm"
                )
            perimeter += length
        if perimeter > MAX_PERIMETER_MM:
            raise ValueError(
                f"total perimeter {perimeter:.0f}mm exceeds the {MAX_PERIMETER_MM:.0f}mm limit"
            )
        ordered_wall_outline(self.walls)
        return self

    def build(self) -> OperationPlan:
        return build(self)


def _box(
    op_id: str, *, length_mm: float, thickness_mm: float, height_mm: float
) -> dict[str, object]:
    """A wall segment lying along +x, its centreline on y=0, starting at the local origin."""
    return {
        "id": op_id,
        "type": "create_box",
        "schema_version": 1,
        "width_mm": length_mm,
        "depth_mm": thickness_mm,
        "height_mm": height_mm,
        "origin_mm": (0.0, -thickness_mm / 2, 0.0),
    }


def _rotate(op_id: str, *, target: str, angle_deg: float) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "rotate",
        "schema_version": 1,
        "target": target,
        "axis": "z",
        "angle_deg": angle_deg,
        "origin_mm": (0.0, 0.0, 0.0),
    }


def _translate(
    op_id: str, *, target: str, offset_mm: tuple[float, float, float]
) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "translate",
        "schema_version": 1,
        "target": target,
        "offset_mm": offset_mm,
    }


def _fuse(op_id: str, *, target: str, tool: str) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "boolean",
        "schema_version": 1,
        "op": "fuse",
        "target": target,
        "tool": tool,
    }


def build(request: HouseWallsRequest) -> OperationPlan:
    """Build one fused solid from hand-drawn wall segments, each extruded to full floor height."""
    height = float(request.floor_height_mm) * request.floors
    operations: list[dict[str, object]] = []
    wall_ids = [f"wall{i}" for i in range(len(request.walls))]

    for wall_id, wall in zip(wall_ids, request.walls, strict=True):
        length = _wall_length(wall)
        angle_deg = math.degrees(math.atan2(wall.b[1] - wall.a[1], wall.b[0] - wall.a[0]))
        operations.append(
            _box(wall_id, length_mm=length, thickness_mm=wall.thickness_mm, height_mm=height)
        )
        operations.append(_rotate(f"{wall_id}_rot", target=wall_id, angle_deg=angle_deg))
        operations.append(
            _translate(f"{wall_id}_pos", target=wall_id, offset_mm=(wall.a[0], wall.a[1], 0.0))
        )

    main = wall_ids[0]
    for wall_id in wall_ids[1:]:
        operations.append(_fuse(f"join_{wall_id}", target=main, tool=wall_id))

    return OperationPlan.model_validate(
        {
            "schema_version": 1,
            "goal": (
                f"{request.floors}-floor freeform house walls from "
                f"{len(request.walls)} drawn segments"
            ),
            "assumptions": [
                "All dimensions are millimetres.",
                "Each wall is extruded to the full stacked floor height; floor slabs and "
                "openings are not generated.",
                "The result is a single fused solid; interior partitions are not separated "
                "from exterior walls.",
            ],
            "operations": operations,
            "validation_steps": [
                "Confirm every wall segment is present and reaches the requested height.",
                "Confirm the fused result is a single solid with no disjoint shells.",
            ],
            "expected_outputs": [main],
        }
    )
