"""House inputs produce a stable, editable 2D plan in millimetres."""

import pytest
from pydantic import ValidationError

from app.engineering.floor_plan import (
    auto_layout_rectangular_plan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
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


def test_rectangular_house_gets_connected_rooms_and_internal_doors() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        shape="rectangle",
    )
    source = floor_plan_from_house_box(request, plan_id="house-floor-1", name="House")

    plan = auto_layout_rectangular_plan(source, room_count=3)

    assert plan.id == source.id and len(plan.rooms) == 3
    assert [_area(room.outline) for room in plan.rooms] == [32_000_000] * 3
    assert len(plan.walls) == 6
    assert len(plan.openings) == 2
    assert [opening.wall for opening in plan.openings] == [4, 5]
    assert all(opening.kind == "door" and opening.width_mm == 900 for opening in plan.openings)

    revised = auto_layout_rectangular_plan(plan, room_count=2)
    assert len(revised.rooms) == 2
    assert len(revised.walls) == 5
    assert [opening.wall for opening in revised.openings] == [4]


def test_auto_layout_refuses_irregular_or_impossibly_small_footprints() -> None:
    irregular = floor_plan_from_house_box(
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=1,
            shape="l_shape",
        ),
        plan_id="l-plan",
        name="L house",
    )
    small = floor_plan_from_house_box(
        HouseBoxRequest(
            length_mm=4_000,
            width_mm=4_000,
            floor_height_mm=3_000,
            floors=1,
            shape="rectangle",
        ),
        plan_id="small-plan",
        name="Small house",
    )

    with pytest.raises(ValueError, match="axis-aligned rectangle"):
        auto_layout_rectangular_plan(irregular, room_count=3)
    with pytest.raises(ValueError, match="too small"):
        auto_layout_rectangular_plan(small, room_count=3)
