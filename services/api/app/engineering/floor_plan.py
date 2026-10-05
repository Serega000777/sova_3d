"""Deterministic 2D plans derived from house-design inputs.

The 3D house builders already know the exact footprint in millimetres.  Keeping the
derived plan beside the immutable project version makes the plan/markup workspace use
the user's real house instead of a demo or a browser-only JSON file.
"""

from __future__ import annotations

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
