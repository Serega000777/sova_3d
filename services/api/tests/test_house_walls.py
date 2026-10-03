"""Freeform house walls: a hand-drawn closed perimeter becomes one fused operation plan."""

import math

import pytest
from pydantic import ValidationError

from app.engineering.house_walls import HouseWallsRequest, PlanWallInput

RECTANGLE = [
    PlanWallInput(a=(0, 0), b=(6000, 0), thickness_mm=120),
    PlanWallInput(a=(6000, 0), b=(6000, 4000), thickness_mm=120),
    PlanWallInput(a=(6000, 4000), b=(0, 4000), thickness_mm=120),
    PlanWallInput(a=(0, 4000), b=(0, 0), thickness_mm=120),
]


def test_closed_rectangle_builds_four_boxes_and_three_fuses() -> None:
    plan = HouseWallsRequest(walls=RECTANGLE, floor_height_mm=3_000, floors=1).build()

    assert plan.expected_outputs == ["wall0"]
    assert [op.type for op in plan.operations].count("create_box") == 4
    assert [op.type for op in plan.operations].count("rotate") == 4
    assert [op.type for op in plan.operations].count("translate") == 4
    booleans = [op for op in plan.operations if op.type == "boolean"]
    assert len(booleans) == 3
    assert all(op.op == "fuse" and op.target == "wall0" for op in booleans)


def test_each_box_matches_its_wall_length_and_total_floor_height() -> None:
    plan = HouseWallsRequest(walls=RECTANGLE, floor_height_mm=2_800, floors=2).build()
    boxes = [op for op in plan.operations if op.type == "create_box"]
    lengths = sorted(round(b.width_mm) for b in boxes)
    assert lengths == [4000, 4000, 6000, 6000]
    assert all(b.height_mm == pytest.approx(5_600) for b in boxes)
    assert all(b.depth_mm == 120 for b in boxes)


def test_rotation_angle_matches_the_wall_direction() -> None:
    plan = HouseWallsRequest(walls=RECTANGLE, floor_height_mm=3_000, floors=1).build()
    rotates = {op.target: op.angle_deg for op in plan.operations if op.type == "rotate"}
    assert rotates["wall0"] == pytest.approx(0.0)  # +x
    assert rotates["wall1"] == pytest.approx(90.0)  # +y
    assert rotates["wall2"] == pytest.approx(180.0)  # -x
    assert rotates["wall3"] == pytest.approx(-90.0)  # -y


def test_translation_places_each_box_at_its_wall_start_point() -> None:
    plan = HouseWallsRequest(walls=RECTANGLE, floor_height_mm=3_000, floors=1).build()
    moves = {op.target: op.offset_mm for op in plan.operations if op.type == "translate"}
    assert moves["wall0"] == (0.0, 0.0, 0.0)
    assert moves["wall1"] == (6000.0, 0.0, 0.0)


def test_a_triangle_is_the_smallest_valid_closed_loop() -> None:
    triangle = [
        PlanWallInput(a=(0, 0), b=(5000, 0), thickness_mm=120),
        PlanWallInput(a=(5000, 0), b=(2500, 4000), thickness_mm=120),
        PlanWallInput(a=(2500, 4000), b=(0, 0), thickness_mm=120),
    ]
    plan = HouseWallsRequest(walls=triangle, floor_height_mm=3_000, floors=1).build()
    assert len([op for op in plan.operations if op.type == "create_box"]) == 3


def test_fewer_than_three_walls_is_rejected() -> None:
    two_walls = RECTANGLE[:2]
    with pytest.raises(ValidationError, match="at least 3 walls"):
        HouseWallsRequest(walls=two_walls, floor_height_mm=3_000, floors=1)


def test_an_open_perimeter_is_rejected_with_a_clear_message() -> None:
    open_walls = RECTANGLE[:3]  # the loop never closes back to (0, 0)
    with pytest.raises(ValidationError, match="do not form a closed perimeter"):
        HouseWallsRequest(walls=open_walls, floor_height_mm=3_000, floors=1)


def test_a_too_short_wall_is_rejected() -> None:
    short = [
        PlanWallInput(a=(0, 0), b=(500, 0), thickness_mm=120),
        PlanWallInput(a=(500, 0), b=(500, 2500), thickness_mm=120),
        PlanWallInput(a=(500, 2500), b=(0, 0), thickness_mm=120),
    ]
    with pytest.raises(ValidationError, match="length"):
        HouseWallsRequest(walls=short, floor_height_mm=3_000, floors=1)


def test_a_too_long_wall_is_rejected() -> None:
    huge = [
        PlanWallInput(a=(0, 0), b=(60_000, 0), thickness_mm=120),
        PlanWallInput(a=(60_000, 0), b=(60_000, 4_000), thickness_mm=120),
        PlanWallInput(a=(60_000, 4_000), b=(0, 0), thickness_mm=120),
    ]
    with pytest.raises(ValidationError, match="length"):
        HouseWallsRequest(walls=huge, floor_height_mm=3_000, floors=1)


def test_an_excessive_perimeter_is_rejected_even_with_in_range_walls() -> None:
    # 10 segments of 45m each is within the per-wall cap but blows the whole-footprint cap
    n = 10
    radius = 45_000.0 / (2 * math.sin(math.pi / n))
    huge_polygon = [
        PlanWallInput(
            a=(
                radius * math.cos(2 * math.pi * i / n),
                radius * math.sin(2 * math.pi * i / n),
            ),
            b=(
                radius * math.cos(2 * math.pi * (i + 1) / n),
                radius * math.sin(2 * math.pi * (i + 1) / n),
            ),
            thickness_mm=120,
        )
        for i in range(n)
    ]
    with pytest.raises(ValidationError, match="perimeter"):
        HouseWallsRequest(walls=huge_polygon, floor_height_mm=3_000, floors=1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("floor_height_mm", 2_199, "greater than or equal to 2200"),
        ("floor_height_mm", 6_001, "less than or equal to 6000"),
        ("floors", 4, "less than or equal to 3"),
        ("floors", 0, "greater than or equal to 1"),
    ],
)
def test_invalid_floor_parameters_are_rejected(field: str, value: float, message: str) -> None:
    kwargs = {"walls": RECTANGLE, "floor_height_mm": 3_000, "floors": 1}
    kwargs[field] = value
    with pytest.raises(ValidationError, match=message):
        HouseWallsRequest(**kwargs)
