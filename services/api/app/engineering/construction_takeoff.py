"""Deterministic construction quantities from a versioned floor plan.

This intentionally stops at measurable geometry.  It does not invent structural norms,
material recipes, supplier prices or a currency estimate.  Those require reviewed external
sources; the quantities here are the stable input for that later pricing layer.
"""

from __future__ import annotations

import math
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.engineering.floor_plan import FloorPlan, PlanRoom, PlanWall

TakeoffUnit = Literal["m", "m2", "m3", "count"]


class TakeoffQuantity(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    quantity: float = Field(ge=0)
    unit: TakeoffUnit
    basis: str = Field(min_length=1, max_length=500)


class ConstructionTakeoff(BaseModel):
    project_id: uuid.UUID
    version_id: uuid.UUID
    plan_id: str
    floors: int = Field(ge=1, le=100)
    floor_height_mm: float | None = Field(default=None, gt=0)
    quantities: list[TakeoffQuantity]
    assumptions: list[str]
    warnings: list[str]
    priced: Literal[False] = False
    currency: None = None


def _r(value: float) -> float:
    return round(value, 6)


def _wall_length_mm(wall: PlanWall) -> float:
    return math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1])


def _room_area_mm2(room: PlanRoom) -> float:
    area = 0.0
    for index, point in enumerate(room.outline):
        other = room.outline[(index + 1) % len(room.outline)]
        area += point[0] * other[1] - other[0] * point[1]
    return abs(area) / 2


def build_construction_takeoff(
    plan: FloorPlan,
    *,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    floors: int = 1,
    floor_height_mm: float | None = None,
) -> ConstructionTakeoff:
    """Measure plan geometry without claiming an engineering or priced estimate."""
    floor_area_m2 = sum(_room_area_mm2(room) for room in plan.rooms) / 1_000_000
    wall_lengths_mm = [_wall_length_mm(wall) for wall in plan.walls]
    wall_length_m = sum(wall_lengths_mm) / 1_000
    quantities = [
        TakeoffQuantity(
            code="footprint_area",
            quantity=_r(floor_area_m2),
            unit="m2",
            basis="sum of room-outline polygon areas on the versioned plan",
        ),
        TakeoffQuantity(
            code="total_floor_area",
            quantity=_r(floor_area_m2 * floors),
            unit="m2",
            basis=f"footprint area multiplied by {floors} floor(s)",
        ),
        TakeoffQuantity(
            code="plan_wall_length",
            quantity=_r(wall_length_m),
            unit="m",
            basis="sum of wall centre-line lengths on the versioned plan",
        ),
    ]
    assumptions = [
        "Room outlines are non-overlapping usable floor regions.",
        "Wall volume uses the centre-line method and each wall's recorded thickness.",
    ]
    warnings = [
        "No supplier prices or structural material norms are applied; "
        "this is not a priced estimate.",
        "Only walls, rooms and openings present on the current plan are counted; "
        "missing interior layout is not inferred.",
    ]

    door_count = sum(opening.kind == "door" for opening in plan.openings)
    window_count = sum(opening.kind == "window" for opening in plan.openings)
    quantities.extend(
        [
            TakeoffQuantity(
                code="door_count",
                quantity=float(door_count),
                unit="count",
                basis="door openings recorded on the versioned plan",
            ),
            TakeoffQuantity(
                code="window_count",
                quantity=float(window_count),
                unit="count",
                basis="window openings recorded on the versioned plan",
            ),
        ]
    )

    if floor_height_mm is None:
        warnings.append(
            "Wall height is unavailable, so wall surface area and volume are not reported."
        )
    else:
        total_height_mm = floor_height_mm * floors
        gross_area_m2 = sum(length * total_height_mm for length in wall_lengths_mm) / 1_000_000
        gross_volume_m3 = sum(
            length * wall.thickness_mm * total_height_mm
            for length, wall in zip(wall_lengths_mm, plan.walls, strict=True)
        ) / 1_000_000_000
        quantities.extend(
            [
                TakeoffQuantity(
                    code="gross_wall_area",
                    quantity=_r(gross_area_m2),
                    unit="m2",
                    basis="plan wall length multiplied by total stacked floor height",
                ),
                TakeoffQuantity(
                    code="gross_wall_volume",
                    quantity=_r(gross_volume_m3),
                    unit="m3",
                    basis="sum of centre-line length × wall thickness × stacked height",
                ),
            ]
        )

    return ConstructionTakeoff(
        project_id=project_id,
        version_id=version_id,
        plan_id=plan.id,
        floors=floors,
        floor_height_mm=floor_height_mm,
        quantities=quantities,
        assumptions=assumptions,
        warnings=warnings,
    )
