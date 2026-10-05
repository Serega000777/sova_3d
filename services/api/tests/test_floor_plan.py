"""House inputs produce a stable, editable 2D plan in millimetres."""

import pytest
from pydantic import ValidationError

from app.engineering.floor_plan import floor_plan_from_house_box, floor_plan_from_house_walls
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest, PlanWallInput


def _area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            x * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * y
            for index, (x, y) in enumerate(points)
        )
        / 2
    )


@pytest.mark.parametrize(
    ("shape", "corners", "area_mm2"),
    [
        ("rectangle", 4, 96_000_000),
        ("l_shape", 6, 72_000_000),
        ("t_shape", 8, 160_000_000 / 3),
    ],
)
def test_house_box_projects_its_real_footprint(
    shape: str, corners: int, area_mm2: float
) -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        shape=shape,  # type: ignore[arg-type]
    )
    plan = floor_plan_from_house_box(request, plan_id="house-floor-1", name="House")

    assert plan.id == "house-floor-1"
    assert len(plan.walls) == corners
    assert len(plan.rooms[0].outline) == corners
    assert _area(plan.rooms[0].outline) == pytest.approx(area_mm2)


def test_freeform_walls_are_ordered_into_one_room_even_when_edges_are_shuffled() -> None:
    request = HouseWallsRequest(
        walls=[
            PlanWallInput(a=(6_000, 4_000), b=(0, 4_000)),
            PlanWallInput(a=(0, 0), b=(6_000, 0)),
            PlanWallInput(a=(0, 4_000), b=(0, 0)),
            PlanWallInput(a=(6_000, 0), b=(6_000, 4_000)),
        ],
        floor_height_mm=3_000,
        floors=1,
    )
    plan = floor_plan_from_house_walls(request, plan_id="drawn-floor-1", name="Drawn house")

    assert len(plan.walls) == 4
    assert _area(plan.rooms[0].outline) == pytest.approx(24_000_000)


def test_disconnected_closed_loops_are_not_accepted_as_one_house() -> None:
    first = [(0.0, 0.0), (3_000.0, 0.0), (1_500.0, 2_600.0)]
    second = [(10_000.0, 0.0), (13_000.0, 0.0), (11_500.0, 2_600.0)]
    walls = [
        PlanWallInput(a=polygon[index], b=polygon[(index + 1) % 3])
        for polygon in (first, second)
        for index in range(3)
    ]

    with pytest.raises(ValidationError, match="single connected loop"):
        HouseWallsRequest(walls=walls, floor_height_mm=3_000, floors=1)
