"""The house quick-start is a validated, deterministic operation plan."""

import itertools
import json
import math
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from worker import geometry as kernel

from app.engineering import house_box
from app.engineering.floor_plan import PlanStair, floor_plans_from_house_box
from app.engineering.house_box import (
    HouseBoxRequest,
    LTurnStairRequest,
    SpiralStairRequest,
    StraightStairRequest,
    UpperFloorSetbackSides,
    UTurnStairRequest,
    WinderTurnStairRequest,
    l_stair_layout,
    l_stair_rail_ids,
    spiral_operation_count,
    spiral_stair_layout,
    u_stair_layout,
    u_stair_rail_ids,
    winder_operation_count,
    winder_stair_layout,
)
from app.geometry.operations import MAX_PLAN_OPERATIONS, CreateBox, Extrude, OperationPlan


def test_single_floor_rectangle_keeps_one_legacy_box() -> None:
    plan = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        shape="rectangle",
    ).build()

    assert plan.expected_outputs == ["house"]
    assert [op.type for op in plan.operations] == ["create_box"]
    box = plan.operations[0]
    assert (box.width_mm, box.depth_mm, box.height_mm) == (12_000, 8_000, 3_000)


@pytest.mark.parametrize(("shape", "boxes", "unions"), [("l_shape", 2, 1), ("t_shape", 3, 2)])
def test_compound_shapes_fuse_multiple_boxes(shape: str, boxes: int, unions: int) -> None:
    plan = HouseBoxRequest(
        length_mm=9_000,
        width_mm=6_000,
        floor_height_mm=2_800,
        floors=1,
        shape=shape,
    ).build()
    assert sum(op.type == "create_box" for op in plan.operations) == boxes
    booleans = [op for op in plan.operations if op.type == "boolean"]
    assert len(booleans) == unions
    assert all(op.op == "fuse" and op.target == "house" for op in booleans)


@pytest.mark.parametrize(
    ("shape", "parts_per_level", "wall_count"),
    [("rectangle", 1, 4), ("l_shape", 2, 6), ("t_shape", 3, 8)],
)
def test_multifloor_shapes_build_separate_exact_shells_and_aligned_plans(
    shape: str, parts_per_level: int, wall_count: int
) -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=9_000,
        floor_height_mm=3_000,
        floors=3,
        shape=shape,  # type: ignore[arg-type]
    )
    plan = request.build()

    assert plan.expected_outputs == ["floor_1", "floor_2", "floor_3", "roof"]
    assert sum(operation.type == "shell" for operation in plan.operations) == 3
    assert sum(operation.type == "create_box" for operation in plan.operations) == (
        4 * parts_per_level
    )
    assert not any(
        operation.type == "boolean" and operation.op == "cut" for operation in plan.operations
    )
    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert [level.elevation_mm for level in floors.levels] == [0, 3_000, 6_000]
    assert [len(level.plan.walls) for level in floors.levels] == [wall_count] * 3
    assert all(
        level.plan.rooms[0].outline == floors.levels[0].plan.rooms[0].outline
        for level in floors.levels
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("length_mm", 1_999, "greater than or equal to 2000"),
        ("width_mm", 50_001, "less than or equal to 50000"),
        ("floor_height_mm", 2_199, "greater than or equal to 2200"),
        ("floors", 4, "less than or equal to 3"),
    ],
)
def test_invalid_dimensions_are_rejected(field: str, value: float, message: str) -> None:
    values = {
        "length_mm": 10_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    values[field] = value
    with pytest.raises(ValidationError, match=message):
        HouseBoxRequest(**values)


def test_straight_stair_builds_separate_floor_shells_openings_and_exact_steps() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        shape="rectangle",
        stair=StraightStairRequest(
            width_mm=1_000,
            tread_depth_mm=280,
            step_count=17,
            placement="center",
            railing=True,
            material_id="interior.wood.oak-natural.v1",
        ),
    )
    plan = request.build()

    assert plan.expected_outputs == [
        "floor_1",
        "floor_2",
        "roof",
        "stair_1_2_step_1",
        "rail_left_1_2",
        "rail_right_1_2",
    ]
    assert len(plan.operations) == 44
    assert sum(operation.type == "shell" for operation in plan.operations) == 2
    cuts = [
        operation
        for operation in plan.operations
        if operation.type == "boolean" and operation.op == "cut"
    ]
    assert len(cuts) == 1 and cuts[0].target == "floor_2"
    steps = [
        operation
        for operation in plan.operations
        if isinstance(operation, CreateBox) and operation.id.startswith("stair_1_2_step_")
    ]
    assert len(steps) == 17
    assert steps[-1].height_mm == pytest.approx(3_000)

    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert [level.elevation_mm for level in floors.levels] == [0, 3_000]
    assert floors.levels[0].plan.stairs[0].role == "up"
    assert floors.levels[1].plan.stairs[0].role == "down"
    assert floors.levels[0].plan.stairs[0].outline == floors.levels[1].plan.stairs[0].outline


def test_maximum_multifloor_stair_stays_within_operation_plan_limit() -> None:
    plan = HouseBoxRequest(
        length_mm=30_000,
        width_mm=10_000,
        floor_height_mm=6_000,
        floors=3,
        shape="rectangle",
        stair=StraightStairRequest(
            width_mm=2_000,
            tread_depth_mm=400,
            step_count=30,
            placement="center",
            railing=True,
        ),
    ).build()
    assert len(plan.operations) == 137
    assert len(plan.operations) <= 256

    with pytest.raises(ValidationError, match="less than or equal to 30"):
        StraightStairRequest(step_count=31)


def test_three_floor_house_accepts_independent_transition_stairs() -> None:
    first = StraightStairRequest(
        width_mm=900,
        tread_depth_mm=280,
        step_count=17,
        placement="left",
        railing=False,
    )
    second = LTurnStairRequest(
        kind="l_turn",
        width_mm=1_000,
        tread_depth_mm=280,
        lower_step_count=8,
        upper_step_count=8,
        placement="right",
        turn="right",
        railing=False,
    )
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=3,
        shape="rectangle",
        stairs=(first, second),
    )

    plan = request.build()
    assert plan.goal == "3-floor house with transition-specific stairs"
    assert "stair_1_2_step_1" in plan.expected_outputs
    assert "stair_2_3_step_1" in plan.expected_outputs
    first_opening = next(op for op in plan.operations if op.id == "stair_opening_2")
    second_opening = next(op for op in plan.operations if op.id == "stair_opening_3_1")
    assert isinstance(first_opening, CreateBox)
    assert isinstance(second_opening, CreateBox)
    assert first_opening.origin_mm[1] < second_opening.origin_mm[1]

    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert [stair.kind for stair in floors.levels[1].plan.stairs] == ["straight", "l_turn"]
    assert floors.levels[0].plan.stairs[0].outline != floors.levels[2].plan.stairs[0].outline


@pytest.mark.parametrize(
    ("stairs", "floors", "message"),
    [
        ((StraightStairRequest(),), 3, "exactly one entry per floor transition"),
        ((StraightStairRequest(),), 1, "exactly one entry per floor transition"),
    ],
)
def test_transition_stair_count_is_fail_closed(
    stairs: tuple[StraightStairRequest, ...], floors: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=floors,  # type: ignore[arg-type]
            shape="rectangle",
            stairs=stairs,
        )


def test_repeated_and_transition_specific_stair_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="either one repeated stair"):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            shape="rectangle",
            stair=StraightStairRequest(),
            stairs=(StraightStairRequest(),),
        )


def test_transition_stairs_validate_only_their_destination_floor_setback() -> None:
    levels = (
        UpperFloorSetbackSides(),
        UpperFloorSetbackSides(y_min_mm=500),
    )
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=3,
        shape="rectangle",
        stairs=(
            StraightStairRequest(placement="left", railing=False),
            StraightStairRequest(placement="right", railing=False),
        ),
        upper_floor_setbacks_mm=levels,
    )
    assert request.build().expected_outputs[-2:] == [
        "stair_1_2_step_1",
        "stair_2_3_step_1",
    ]

    with pytest.raises(ValueError, match="does not fit inside the setback upper floor"):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=3,
            shape="rectangle",
            stairs=(
                StraightStairRequest(placement="left", railing=False),
                StraightStairRequest(placement="left", railing=False),
            ),
            upper_floor_setbacks_mm=levels,
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            dict(
                length_mm=12_000,
                width_mm=8_000,
                floor_height_mm=3_000,
                floors=1,
                shape="rectangle",
                stair=StraightStairRequest(),
            ),
            "at least two floors",
        ),
        (
            dict(
                length_mm=12_000,
                width_mm=8_000,
                floor_height_mm=3_000,
                floors=2,
                shape="l_shape",
                stair=StraightStairRequest(),
            ),
            "rectangular house",
        ),
        (
            dict(
                length_mm=4_000,
                width_mm=3_000,
                floor_height_mm=3_000,
                floors=2,
                shape="rectangle",
                stair=StraightStairRequest(step_count=17, tread_depth_mm=280),
            ),
            "do not fit",
        ),
        (
            dict(
                length_mm=12_000,
                width_mm=8_000,
                floor_height_mm=6_000,
                floors=2,
                shape="rectangle",
                stair=StraightStairRequest(step_count=10),
            ),
            "120-220 mm rise",
        ),
    ],
)
def test_invalid_stair_relationships_fail_before_kernel(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        HouseBoxRequest(**payload)


def _l_request(**stair: object) -> HouseBoxRequest:
    values: dict[str, object] = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    values.update(stair.pop("house", {}))  # type: ignore[arg-type]
    return HouseBoxRequest(**values, stair=LTurnStairRequest(kind="l_turn", **stair))


@pytest.mark.parametrize("turn", ["left", "right"])
def test_l_turn_stair_builds_one_fused_flight_landing_and_l_openings(turn: str) -> None:
    request = _l_request(lower_step_count=8, upper_step_count=8, turn=turn, railing=True)
    plan = request.build()

    assert plan.goal == "2-floor house with an L-turn stair"
    assert plan.expected_outputs == [
        "floor_1",
        "floor_2",
        "roof",
        "stair_1_2_step_1",
        *l_stair_rail_ids(0),
    ]
    # 2 shells + 2 openings with cuts + roof + 17 bodies/16 fuses + 4 sloped + 2 landing rails
    assert len(plan.operations) == 4 + 4 + 1 + 33 + 8 + 2
    cuts = [op for op in plan.operations if op.type == "boolean" and op.op == "cut"]
    assert [op.target for op in cuts] == ["floor_2", "floor_2"]
    fuses = [op for op in plan.operations if op.type == "boolean" and op.op == "fuse"]
    assert len(fuses) == 16 and {op.target for op in fuses} == {"stair_1_2_step_1"}

    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    rise = 3_000 / 17
    landing = boxes["stair_1_2_landing"]
    assert landing.height_mm == pytest.approx(rise * 9)
    assert (landing.width_mm, landing.depth_mm) == (1_000, 1_000)
    top = boxes["stair_1_2_step_16"]
    assert top.height_mm == pytest.approx(3_000)
    assert (top.width_mm, top.depth_mm) == (1_000, 280)
    landing_y = landing.origin_mm[1]
    if turn == "left":
        assert boxes["stair_1_2_step_9"].origin_mm[1] == pytest.approx(landing_y + 1_000)
        assert top.origin_mm[1] == pytest.approx(landing_y + 1_000 + 7 * 280)
    else:
        assert boxes["stair_1_2_step_9"].origin_mm[1] == pytest.approx(landing_y - 280)
        assert top.origin_mm[1] == pytest.approx(landing_y - 8 * 280)
    rotations = [op for op in plan.operations if op.type == "rotate"]
    assert sorted(op.axis for op in rotations) == ["x", "x", "y", "y"]

    layout = l_stair_layout(request)
    min_xs = [x for x, _ in layout.outline]
    min_ys = [y for _, y in layout.outline]
    assert min(min_xs) >= 350 and max(min_xs) <= 12_000 - 350
    assert min(min_ys) >= 350 and max(min_ys) <= 8_000 - 350


def test_l_turn_floor_plans_share_one_l_footprint_with_flights_and_landing() -> None:
    request = _l_request(
        house={"floors": 3}, lower_step_count=9, upper_step_count=7, turn="right", railing=False
    )
    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert [len(level.plan.stairs) for level in floors.levels] == [1, 2, 1]
    up = floors.levels[0].plan.stairs[0]
    down = floors.levels[1].plan.stairs[0]
    assert (up.role, down.role) == ("up", "down")
    assert up.kind == "l_turn" and up.turn == "right"
    assert len(up.outline) == 6 and up.outline == down.outline
    assert [flight.step_count for flight in up.flights] == [9, 7]
    assert [flight.direction for flight in up.flights] == ["+x", "-y"]
    assert up.step_count == 17 and up.riser_height_mm == pytest.approx(3_000 / 17)
    assert up.run_mm == pytest.approx(280 * 16)
    assert up.landing is not None
    area = 0.0
    for index, (x0, y0) in enumerate(up.outline):
        x1, y1 = up.outline[(index + 1) % 6]
        area += x0 * y1 - x1 * y0
    assert abs(area) / 2 == pytest.approx(1_000 * (280 * 16 + 1_000))

    with pytest.raises(ValidationError, match="landing must equal the riser count"):
        PlanStair.model_validate({**up.model_dump(), "step_count": 18})
    with pytest.raises(ValidationError, match="6-point outline"):
        PlanStair.model_validate({**up.model_dump(), "outline": up.outline[:4]})


def test_maximum_l_turn_stair_stays_within_operation_plan_limit() -> None:
    plan = _l_request(
        house={"length_mm": 30_000, "width_mm": 12_000, "floor_height_mm": 4_350, "floors": 3},
        width_mm=2_000,
        tread_depth_mm=300,
        lower_step_count=15,
        upper_step_count=14,
        placement="left",
        railing=True,
    ).build()
    assert len(plan.operations) == 153
    assert len(plan.operations) <= 256

    with pytest.raises(ValidationError, match="10-30 risers"):
        _l_request(
            house={"length_mm": 30_000, "width_mm": 12_000, "floor_height_mm": 4_650},
            width_mm=2_000,
            tread_depth_mm=300,
            lower_step_count=15,
            upper_step_count=15,
        )


@pytest.mark.parametrize(
    ("house", "stair", "message"),
    [
        ({"length_mm": 3_900}, {}, "do not fit"),
        ({"width_mm": 3_500}, {}, "do not fit"),
        (
            {"width_mm": 6_000},
            {"placement": "left", "width_mm": 2_000, "lower_step_count": 4, "upper_step_count": 12},
            "do not fit",
        ),
        ({"floor_height_mm": 6_000}, {}, "120-220 mm rise"),
        ({"floor_height_mm": 2_200}, {"lower_step_count": 10, "upper_step_count": 9}, "rise"),
        ({}, {"tread_depth_mm": 400}, "550-700 mm"),
        ({}, {"width_mm": 699}, "greater than or equal to 700"),
        ({}, {"width_mm": 2_001}, "less than or equal to 2000"),
        ({}, {"lower_step_count": 2}, "greater than or equal to 3"),
        ({"floors": 1}, {}, "at least two floors"),
        ({"shape": "t_shape"}, {}, "rectangular house"),
    ],
)
def test_invalid_l_turn_stairs_fail_before_kernel(
    house: dict[str, object], stair: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _l_request(house=house, **stair)


def test_stored_requests_without_kind_stay_straight_and_kinds_do_not_mix() -> None:
    legacy = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        stair={"width_mm": 1_000, "tread_depth_mm": 280, "step_count": 17},  # type: ignore[arg-type]
    )
    assert isinstance(legacy.stair, StraightStairRequest)
    assert asdict(legacy.stair)["kind"] == "straight"
    restored = HouseBoxRequest(**asdict(_l_request(turn="right")))
    assert isinstance(restored.stair, LTurnStairRequest) and restored.stair.turn == "right"
    with pytest.raises(ValidationError):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            stair={"kind": "l_turn", "step_count": 17},  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            stair={"kind": "helical"},  # type: ignore[arg-type]
        )


def _u_request(**stair: object) -> HouseBoxRequest:
    values: dict[str, object] = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    values.update(stair.pop("house", {}))  # type: ignore[arg-type]
    return HouseBoxRequest(**values, stair=UTurnStairRequest(kind="u_turn", **stair))


@pytest.mark.parametrize("turn", ["left", "right"])
def test_u_turn_stair_builds_parallel_flights_full_landing_and_one_opening(turn: str) -> None:
    request = _u_request(flight_step_count=8, turn=turn, railing=True)
    plan = request.build()

    assert plan.goal == "2-floor house with a U-turn stair"
    assert plan.expected_outputs == [
        "floor_1",
        "floor_2",
        "roof",
        "stair_1_2_step_1",
        *u_stair_rail_ids(0),
    ]
    assert len(plan.operations) == 51
    cuts = [op for op in plan.operations if op.type == "boolean" and op.op == "cut"]
    assert len(cuts) == 1 and cuts[0].target == "floor_2"
    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    rise = 3_000 / 17
    landing = boxes["stair_1_2_landing"]
    assert (landing.width_mm, landing.depth_mm, landing.height_mm) == pytest.approx(
        (1_000, 2_000, rise * 9)
    )
    top = boxes["stair_1_2_step_16"]
    assert top.height_mm == pytest.approx(3_000)
    layout = u_stair_layout(request)
    assert top.origin_mm[0] == pytest.approx(layout.upper[0])
    assert layout.outline[0][1] == pytest.approx(min(layout.lower[1], layout.upper[1]))
    assert layout.outline[2][1] == pytest.approx(max(layout.lower[3], layout.upper[3]))
    rotations = [op for op in plan.operations if op.type == "rotate"]
    assert len(rotations) == 4 and {op.axis for op in rotations} == {"y"}


def test_u_turn_floor_plans_preserve_equal_parallel_flights() -> None:
    request = _u_request(house={"floors": 3}, flight_step_count=8, turn="right")
    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    up = floors.levels[0].plan.stairs[0]
    assert up.kind == "u_turn" and up.turn == "right"
    assert len(up.outline) == 4 and len(up.flights) == 2
    assert [flight.direction for flight in up.flights] == ["+x", "-x"]
    assert [flight.step_count for flight in up.flights] == [8, 8]
    assert up.step_count == 17 and up.run_mm == 280 * 16
    assert up.landing is not None

    with pytest.raises(ValidationError, match="equal step counts"):
        payload = up.model_dump()
        payload["flights"][1]["step_count"] = 7
        payload["step_count"] = 16
        PlanStair.model_validate(payload)


def test_maximum_u_turn_stair_stays_within_operation_plan_limit() -> None:
    plan = _u_request(
        house={"length_mm": 30_000, "width_mm": 12_000, "floor_height_mm": 4_350, "floors": 3},
        width_mm=2_000,
        tread_depth_mm=300,
        flight_step_count=14,
        placement="left",
        railing=True,
    ).build()
    assert len(plan.operations) == 147
    assert len(plan.operations) <= 256


@pytest.mark.parametrize(
    ("house", "stair", "message"),
    [
        ({"length_mm": 3_900}, {}, "do not fit"),
        ({"width_mm": 2_600}, {}, "do not fit"),
        ({"floor_height_mm": 6_000}, {}, "120-220 mm rise"),
        ({}, {"tread_depth_mm": 400}, "550-700 mm"),
        ({}, {"flight_step_count": 4}, "greater than or equal to 5"),
        ({}, {"flight_step_count": 15}, "less than or equal to 14"),
    ],
)
def test_invalid_u_turn_stairs_fail_before_kernel(
    house: dict[str, object], stair: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _u_request(house=house, **stair)


def _winder_request(house: dict[str, Any] | None = None, **stair: Any) -> HouseBoxRequest:
    values: dict[str, Any] = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
        **(house or {}),
    }
    return HouseBoxRequest(**values, stair=WinderTurnStairRequest(kind="winder_turn", **stair))


XY = tuple[float, float]


def _area(polygon: list[XY]) -> float:
    """Signed shoelace area: positive means counter-clockwise."""
    return (
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1], strict=True)
        )
        / 2
    )


def _inside(point: XY, polygon: list[XY]) -> bool:
    x, y = point
    hit = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _plan_polygons(plan: OperationPlan) -> dict[str, list[XY]]:
    """Every stair tread of the generated plan as a plan-space polygon, by operation id."""
    polygons: dict[str, list[XY]] = {}
    for op in plan.operations:
        if not op.id.startswith("stair_") or op.id.startswith("stair_opening"):
            continue
        if isinstance(op, CreateBox):
            x, y, _ = op.origin_mm
            polygons[op.id] = [
                (x, y),
                (x + op.width_mm, y),
                (x + op.width_mm, y + op.depth_mm),
                (x, y + op.depth_mm),
            ]
        elif isinstance(op, Extrude):
            assert op.profile.kind == "polygon"
            polygons[op.id] = [(x, y) for x, y in op.profile.points_mm]
    return polygons


@pytest.mark.parametrize("turn", ["left", "right"])
def test_winder_stair_builds_two_flights_three_polygons_and_one_output(turn: str) -> None:
    request = _winder_request(turn=turn)
    plan = request.build()
    layout = winder_stair_layout(request)
    rise = 3_000 / 17

    assert plan.goal == "2-floor house with a winder-turn stair"
    assert plan.expected_outputs == ["floor_1", "floor_2", "roof", "stair_1_2_step_1"]
    # 2 shells + 2 openings with cuts + roof + 17 bodies/16 fuses
    assert len(plan.operations) == 4 + 4 + 1 + 33 == winder_operation_count(request)
    cuts = [op for op in plan.operations if op.type == "boolean" and op.op == "cut"]
    assert [(op.target, op.tool) for op in cuts] == [
        ("floor_2", "stair_opening_2_1"),
        ("floor_2", "stair_opening_2_2"),
    ]
    fuses = [op for op in plan.operations if op.type == "boolean" and op.op == "fuse"]
    assert len(fuses) == 16 and {op.target for op in fuses} == {"stair_1_2_step_1"}

    winders = [op for op in plan.operations if isinstance(op, Extrude)]
    assert [op.id for op in winders] == [f"stair_1_2_winder_{i}" for i in (1, 2, 3)]
    assert [op.height_mm for op in winders] == pytest.approx([rise * i for i in (8, 9, 10)])
    assert all(op.normal == (0, 0, 1) and op.origin_mm == (0, 0, 0) for op in winders)
    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    steps = [boxes[f"stair_1_2_step_{index}"] for index in range(1, 15)]
    assert [op.height_mm for op in steps[7:]] == pytest.approx([rise * i for i in range(11, 18)])
    assert steps[-1].height_mm == pytest.approx(3_000)

    # The lower flight climbs +X into the turn box, the upper one leaves it along ±Y.
    assert [op.origin_mm[0] for op in steps[:7]] == pytest.approx(
        [layout.lower[0] + 280 * index for index in range(7)]
    )
    assert {op.origin_mm[1] for op in steps[:7]} == {layout.lower[1]}
    if turn == "left":
        expected_y = [layout.upper[1] + 280 * index for index in range(7)]
    else:
        expected_y = [layout.upper[3] - 280 * (index + 1) for index in range(7)]
    assert [op.origin_mm[1] for op in steps[7:]] == pytest.approx(expected_y)


def _winder_edges_shared(first: list[XY], second: list[XY]) -> set[XY]:
    return set(first) & set(second)


@pytest.mark.parametrize("turn", ["left", "right"])
@pytest.mark.parametrize(
    ("width", "newel", "tread"),
    [
        (1_000.0, 250.0, 280.0),
        (700.0, 200.0, 280.0),
        (2_000.0, 200.0, 280.0),
        (933.3, 233.3, 277.7),
    ],
)
def test_winder_polygons_are_exact_for_both_turns(
    turn: str, width: float, newel: float, tread: float
) -> None:
    request = _winder_request(turn=turn, width_mm=width, newel_mm=newel, tread_depth_mm=tread)
    layout = winder_stair_layout(request)
    polygons = _plan_polygons(request.build())
    winders = [polygons[f"stair_1_2_winder_{index}"] for index in (1, 2, 3)]
    size = width + newel
    tx0, ty0, tx1, ty1 = layout.turn_box
    assert (tx1 - tx0, ty1 - ty0) == pytest.approx((size, size))

    # Counter-clockwise for BOTH turns, so a mirrored right-turn prism is never inside-out.
    areas = [_area(winder) for winder in winders]
    assert all(area > 0 for area in areas)
    assert sum(areas) == pytest.approx(size**2 - newel**2)
    assert areas[0] == pytest.approx(areas[2])
    # A tread between riser rays at 0°/30°: big triangle minus the newel's triangle.
    assert areas[0] == pytest.approx((size**2 - newel**2) * math.tan(math.pi / 6) / 2)

    # All four riser edges aim at the newel's far corner and are exactly 30° apart.
    pivot = (tx0, ty1 if turn == "left" else ty0)
    lower_x = layout.lower[2]
    up_y = layout.upper[1] if turn == "left" else layout.upper[3]
    risers: list[set[XY]] = [
        {(lower_x, layout.lower[1]), (lower_x, layout.lower[3])},
        _winder_edges_shared(winders[0], winders[1]),
        _winder_edges_shared(winders[1], winders[2]),
        {(layout.upper[0], up_y), (layout.upper[2], up_y)},
    ]
    angles: list[float] = []
    for riser in risers:
        assert len(riser) == 2
        rays = [math.atan2(abs(x - pivot[0]), abs(y - pivot[1])) for x, y in riser]
        assert rays[0] == pytest.approx(rays[1], abs=1e-9)
        angles.append(math.degrees(rays[0]))
    assert angles == pytest.approx([0, 30, 60, 90], abs=1e-6)

    # The newel square stays open: no tread covers any of it and its side never collapses.
    nx0, ny0, nx1, ny1 = layout.newel
    assert (nx1 - nx0, ny1 - ny0) == pytest.approx((newel, newel))
    for fx, fy in itertools.product((0.02, 0.5, 0.98), repeat=2):
        probe = (nx0 + fx * newel, ny0 + fy * newel)
        assert not any(_inside(probe, polygon) for polygon in polygons.values())

    # Treads tile the swept outline without overlapping (areas add up exactly).
    outline = layout.outline
    assert len(outline) == 6 and _area(outline) > 0
    assert sum(abs(_area(polygon)) for polygon in polygons.values()) == pytest.approx(
        _area(outline)
    )


def test_winder_right_turn_is_the_exact_mirror_of_the_left_turn() -> None:
    left = _plan_polygons(_winder_request(turn="left").build())
    right = _plan_polygons(_winder_request(turn="right").build())
    assert left.keys() == right.keys()
    for name, polygon in left.items():
        mirrored = sorted((x, 8_000 - y) for x, y in polygon)
        assert [value for point in sorted(right[name]) for value in point] == pytest.approx(
            [value for point in mirrored for value in point]
        )


@pytest.mark.parametrize("turn", ["left", "right"])
@pytest.mark.parametrize("placement", ["left", "center", "right"])
def test_winder_openings_cover_the_swept_footprint_and_keep_clearance(
    turn: str, placement: str
) -> None:
    request = _winder_request(
        house={"floors": 3}, turn=turn, placement=placement, lower_step_count=6, upper_step_count=8
    )
    plan = request.build()
    layout = winder_stair_layout(request)
    assert plan.expected_outputs[-2:] == ["stair_1_2_step_1", "stair_2_3_step_1"]
    for floor in (2, 3):
        openings = [
            op
            for op in plan.operations
            if isinstance(op, CreateBox) and op.id.startswith(f"stair_opening_{floor}_")
        ]
        assert len(openings) == 2
        rects = [
            (
                op.origin_mm[0],
                op.origin_mm[1],
                op.origin_mm[0] + op.width_mm,
                op.origin_mm[1] + op.depth_mm,
            )
            for op in openings
        ]
        for polygon in _plan_polygons(plan).values():
            for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
                for t in (0.0, 0.25, 0.5, 0.75):
                    x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                    # Each boundary point keeps the full 50 mm opening margin on both axes.
                    assert any(
                        x0 + 49.999 <= x <= x1 - 49.999 and y0 + 49.999 <= y <= y1 - 49.999
                        for x0, y0, x1, y1 in rects
                    )
        # The slab beside both flights is not cut away with the bounding rectangle.
        corner = (
            layout.lower[0] + 100,
            layout.upper[3] - 100 if turn == "left" else layout.upper[1] + 100,
        )
        assert not any(x0 <= corner[0] <= x1 and y0 <= corner[1] <= y1 for x0, y0, x1, y1 in rects)
    xs = [x for x, _ in layout.outline]
    ys = [y for _, y in layout.outline]
    assert min(xs) >= 350 and max(xs) <= 12_000 - 350
    assert min(ys) >= 350 and max(ys) <= 8_000 - 350


@pytest.mark.parametrize("turn", ["left", "right"])
def test_winder_floor_plans_share_outline_flights_winders_and_newel(turn: str) -> None:
    request = _winder_request(
        house={"floors": 3}, lower_step_count=6, upper_step_count=8, turn=turn
    )
    layout = winder_stair_layout(request)
    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert [len(level.plan.stairs) for level in floors.levels] == [1, 2, 1]
    up = floors.levels[0].plan.stairs[0]
    down = floors.levels[1].plan.stairs[0]
    assert (up.role, down.role) == ("up", "down")
    assert up.kind == "winder_turn" and up.turn == turn and up.railing is False
    assert up.outline == layout.outline == down.outline
    assert [flight.step_count for flight in up.flights] == [6, 8]
    assert [flight.direction for flight in up.flights] == ["+x", "+y" if turn == "left" else "-y"]
    assert up.step_count == 17 and up.run_mm == 280 * 14 and up.landing is None
    assert [tuple(winder) for winder in up.winders] == list(layout.winders)
    assert up.newel is not None and len(up.newel) == 4
    # Stored JSON restores to the same proven stair.
    assert PlanStair.model_validate_json(up.model_dump_json()) == up

    payload = up.model_dump()
    broken: list[tuple[dict[str, Any], str]] = [
        ({"step_count": 18}, "three winders must equal"),
        ({"outline": up.outline[:4]}, "6-point outline"),
        ({"winders": up.winders[:2]}, "three winders"),
        ({"newel": None}, "newel"),
        ({"landing": up.newel}, "no landing"),
        ({"railing": True}, "no modelled railing"),
        ({"turn": "left" if turn == "right" else "right"}, "must climb"),
        ({"kind": "l_turn"}, "only a winder-turn stair"),
    ]
    for change, message in broken:
        with pytest.raises(ValidationError, match=message):
            PlanStair.model_validate({**payload, **change})
    moved = [[(x + 1, y) for x, y in up.winders[0]], *up.winders[1:]]
    with pytest.raises(ValidationError, match="share exactly one riser edge"):
        PlanStair.model_validate({**payload, "winders": moved})


def test_maximum_winder_stair_stays_within_operation_plan_limit() -> None:
    house = {"length_mm": 30_000, "width_mm": 12_000, "floor_height_mm": 4_350, "floors": 3}
    largest = _winder_request(
        house=house,
        width_mm=2_000,
        tread_depth_mm=300,
        lower_step_count=14,
        upper_step_count=13,
        placement="left",
    )
    plan = largest.build()
    # 3 shells, 2 x 2 openings with cuts, roof, 2 x (30 bodies + 29 fuses); no rail operations.
    assert len(plan.operations) == 6 + 8 + 1 + 2 * 59 == 133 == winder_operation_count(largest)
    assert len(plan.operations) <= MAX_PLAN_OPERATIONS == 256
    # Flight bounds alone cannot exceed the riser ceiling either.
    extreme = _winder_request(
        house={**house, "floor_height_mm": 3_750},
        tread_depth_mm=300,
        newel_mm=320,
        lower_step_count=24,
        upper_step_count=3,
    )
    assert len(extreme.build().operations) == 133

    with pytest.raises(ValidationError, match="10-30 risers"):
        _winder_request(
            house=house,
            width_mm=2_000,
            tread_depth_mm=300,
            lower_step_count=14,
            upper_step_count=14,
        )


def test_every_accepted_winder_riser_total_matches_the_derived_operation_count() -> None:
    # 10 risers would need a 220 mm rise, which the winder walking-line rule already rejects.
    for floors, total in itertools.product((2, 3), range(11, 31)):
        lower = (total - 3) // 2
        request = _winder_request(
            house={
                "length_mm": 30_000,
                "width_mm": 30_000,
                "floors": floors,
                "floor_height_mm": max(2_200, 165 * total),
            },
            tread_depth_mm=250,
            newel_mm=200,
            lower_step_count=lower,
            upper_step_count=total - 3 - lower,
        )
        assert len(request.build().operations) == winder_operation_count(request)
        assert winder_operation_count(request) <= 133


@pytest.mark.parametrize(
    ("house", "stair", "message"),
    [
        ({"length_mm": 3_900}, {}, "do not fit"),
        ({"width_mm": 3_900}, {}, "do not fit"),
        ({"width_mm": 3_909}, {"placement": "left"}, "do not fit"),
        ({"floor_height_mm": 6_000}, {}, "120-220 mm rise"),
        ({"floor_height_mm": 2_200}, {"lower_step_count": 8, "upper_step_count": 8}, "rise"),
        ({}, {"tread_depth_mm": 400}, "550-700 mm for a turning stair"),
        ({}, {"newel_mm": 500}, "winder walking-line going"),
        ({}, {"lower_step_count": 3, "upper_step_count": 3}, "10-30 risers"),
        (
            {"floor_height_mm": 2_200},
            {"lower_step_count": 3, "upper_step_count": 4, "newel_mm": 200, "tread_depth_mm": 250},
            "winder walking-line going",
        ),
        ({}, {"width_mm": 699.9}, "greater than or equal to 700"),
        ({}, {"width_mm": 2_000.1}, "less than or equal to 2000"),
        ({}, {"width_mm": "1000"}, "valid number"),
        ({}, {"width_mm": math.nan}, "finite"),
        ({}, {"tread_depth_mm": 199}, "greater than or equal to 200"),
        ({}, {"newel_mm": 199.9}, "greater than or equal to 200"),
        ({}, {"newel_mm": 500.1}, "less than or equal to 500"),
        ({}, {"newel_mm": True}, "valid number"),
        ({}, {"lower_step_count": 2}, "greater than or equal to 3"),
        ({}, {"upper_step_count": 25}, "less than or equal to 24"),
        ({}, {"lower_step_count": 7.0}, "valid integer"),
        ({}, {"lower_step_count": "7"}, "valid integer"),
        ({}, {"railing": True}, "Input should be False"),
        ({}, {"turn": "up"}, "'left' or 'right'"),
        ({}, {"step_count": 17}, "Unexpected keyword"),
        ({}, {"winder_count": 4}, "Unexpected keyword"),
        ({"floors": 1}, {}, "at least two floors"),
        ({"shape": "l_shape"}, {}, "rectangular house"),
        ({"shape": "t_shape"}, {}, "rectangular house"),
        ({"upper_floor_setback_mm": 2_100}, {}, "setback upper floor"),
        ({"upper_floor_setback_mm": 1}, {"placement": "left"}, "setback upper floor"),
    ],
)
def test_invalid_winder_stairs_fail_before_kernel(
    house: dict[str, object], stair: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _winder_request(house=house, **stair)


def test_winder_footprint_accepts_the_exact_clearance_boundary() -> None:
    # 7 × 280 + 1 000 + 250 = 3 210 mm plus 350 mm on both sides.
    exact = {"length_mm": 3_910, "width_mm": 3_910}
    for placement in ("left", "center", "right"):
        layout = winder_stair_layout(_winder_request(house=exact, placement=placement))
        assert layout.outline[0] == pytest.approx((350, 350))
    with pytest.raises(ValidationError, match="do not fit"):
        _winder_request(house={**exact, "length_mm": 3_909.9})


def test_collapsed_or_disconnected_winder_layouts_fail_closed() -> None:
    layout = winder_stair_layout(_winder_request())
    first, middle, last = layout.winders
    cases = [
        ((tuple(reversed(first)), middle, last), "counter-clockwise"),
        (((first[0], first[2], first[1], first[3]), middle, last), "simple counter-clockwise"),
        (((first[0], first[0], first[2], first[3]), middle, last), "collapses"),
        ((tuple((x + 60, y) for x, y in first), middle, last), "share a riser edge"),
        ((first, middle), "do not tile"),
    ]
    for winders, message in cases:
        with pytest.raises(ValueError, match=message):
            house_box._validate_winder_layout(replace(layout, winders=winders))


def test_winder_request_round_trips_and_kinds_do_not_mix() -> None:
    restored = HouseBoxRequest(**asdict(_winder_request(turn="right", newel_mm=300)))
    assert isinstance(restored.stair, WinderTurnStairRequest)
    assert restored.stair.turn == "right" and restored.stair.newel_mm == 300
    assert restored.build() == _winder_request(turn="right", newel_mm=300).build()
    base = {"length_mm": 12_000, "width_mm": 8_000, "floor_height_mm": 3_000, "floors": 2}
    for stair in (
        {"kind": "winder_turn", "flight_step_count": 8},
        {"kind": "l_turn", "newel_mm": 250},
        {"kind": "u_turn", "newel_mm": 250},
        {"newel_mm": 250},
    ):
        with pytest.raises(ValidationError):
            HouseBoxRequest(**base, stair=stair)  # type: ignore[arg-type]


@pytest.mark.skipif(not kernel.available(), reason="geometry-service binary is not installed")
@pytest.mark.parametrize("turn", ["left", "right"])
def test_real_kernel_fuses_each_winder_flight_into_one_exact_solid(
    turn: str, tmp_path: Path
) -> None:
    request = _winder_request(house={"floors": 3}, turn=turn)
    plan = request.build()
    result = kernel.execute_plan(plan.model_dump(mode="json"), tmp_path / "out")
    assert result.ok, result.error
    bodies = {body.name: body for body in result.bodies}
    assert set(plan.expected_outputs) <= set(bodies)
    layout = winder_stair_layout(request)
    flight_area = layout.tread * layout.width
    volume = sum(
        layout.rise
        * riser
        * (_area(list(layout.winders[riser - 8])) if 8 <= riser <= 10 else flight_area)
        for riser in range(1, 18)
    )
    for name in ("stair_1_2_step_1", "stair_2_3_step_1"):
        assert bodies[name].solids == 1 and bodies[name].valid
        assert bodies[name].volume_mm3 == pytest.approx(volume, rel=1e-9)
    assert all(bodies[f"floor_{n}"].valid and bodies[f"floor_{n}"].solids == 1 for n in (1, 2, 3))


def test_upper_floor_setback_offsets_shell_roof_and_floor_plans() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=3,
        upper_floor_setback_mm=500,
    )
    plan = request.build()
    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    assert boxes["floor_1"].origin_mm == (0.0, 0.0, 0.0)
    assert boxes["floor_2"].origin_mm == (500.0, 500.0, 3_000.0)
    assert (boxes["floor_2"].width_mm, boxes["floor_2"].depth_mm) == (11_000.0, 7_000.0)
    assert boxes["floor_3"].origin_mm == (500.0, 500.0, 6_000.0)
    assert boxes["roof"].origin_mm == (500.0, 500.0, 9_000.0)

    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert floors.levels[0].plan.rooms[0].outline[0] == (0.0, 0.0)
    assert floors.levels[1].plan.rooms[0].outline == [
        (500.0, 500.0),
        (11_500.0, 500.0),
        (11_500.0, 7_500.0),
        (500.0, 7_500.0),
    ]


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"floors": 1, "upper_floor_setback_mm": 200}, "at least two floors"),
        ({"shape": "l_shape", "upper_floor_setback_mm": 200}, "rectangular house"),
        ({"length_mm": 4_000, "upper_floor_setback_mm": 1_001}, "at least 2000 mm"),
    ],
)
def test_invalid_upper_floor_setback_fails_before_kernel(
    values: dict[str, object], message: str
) -> None:
    request = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        **values,
    }
    with pytest.raises(ValidationError, match=message):
        HouseBoxRequest(**request)  # type: ignore[arg-type]


def test_stair_must_fit_inside_setback_upper_floor() -> None:
    with pytest.raises(ValidationError, match="does not fit inside the setback upper floor"):
        HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            upper_floor_setback_mm=1_500,
            stair=StraightStairRequest(placement="left"),
        )


def test_per_side_setback_offsets_shell_roof_plans_and_keeps_symmetric_plan() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=3,
        upper_floor_setback_sides_mm=UpperFloorSetbackSides(x_max_mm=3_000, y_min_mm=1_000),
    )
    plan = request.build()
    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    assert boxes["floor_1"].origin_mm == (0.0, 0.0, 0.0)
    assert (boxes["floor_1"].width_mm, boxes["floor_1"].depth_mm) == (12_000.0, 8_000.0)
    for body, z in (("floor_2", 3_000.0), ("floor_3", 6_000.0), ("roof", 9_000.0)):
        assert boxes[body].origin_mm == (0.0, 1_000.0, z)
        assert (boxes[body].width_mm, boxes[body].depth_mm) == (9_000.0, 7_000.0)
    assert "per-side setback" in " ".join(plan.assumptions)

    floors = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    )
    assert floors.levels[1].plan.rooms[0].outline == [
        (0.0, 1_000.0),
        (9_000.0, 1_000.0),
        (9_000.0, 8_000.0),
        (0.0, 8_000.0),
    ]

    # Equal sides describe the same geometry as the historical symmetric field.
    symmetric = replace(
        request, upper_floor_setback_sides_mm=None, upper_floor_setback_mm=500
    ).build()
    equal_sides = replace(
        request,
        upper_floor_setback_sides_mm=UpperFloorSetbackSides(
            x_min_mm=500, x_max_mm=500, y_min_mm=500, y_max_mm=500
        ),
    ).build()
    assert equal_sides.operations == symmetric.operations


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"upper_floor_setback_mm": 200, "sides": {"x_min_mm": 100}}, "not both"),
        ({"sides": {}}, "at least one positive side"),
        ({"floors": 1, "sides": {"x_min_mm": 100}}, "at least two floors"),
        ({"shape": "t_shape", "sides": {"x_min_mm": 100}}, "rectangular house"),
        ({"sides": {"x_min_mm": 5_000, "x_max_mm": 5_001}}, "at least 2000 mm"),
        ({"sides": {"y_min_mm": 6_001}}, "at least 2000 mm"),
        ({"sides": {"x_min_mm": -1}}, "greater than or equal"),
        ({"sides": {"x_min_mm": 10_001}}, "less than or equal"),
        ({"sides": {"x_min_mm": float("nan")}}, "finite"),
        ({"sides": {"x_min_mm": "100"}}, "valid number"),
        ({"sides": {"front_mm": 100}}, "front_mm"),
    ],
)
def test_invalid_per_side_setback_fails_before_kernel(values: dict[str, Any], message: str) -> None:
    sides = values.pop("sides")
    request = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        **values,
        "upper_floor_setback_sides_mm": sides,
    }
    with pytest.raises(ValidationError, match=message):
        HouseBoxRequest(**request)


def test_stair_against_a_set_back_wall_fails_but_opposite_wall_fits() -> None:
    def house(stair: Any, **sides: float) -> HouseBoxRequest:
        return HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=2,
            upper_floor_setback_sides_mm=UpperFloorSetbackSides(**sides),
            stair=stair,
        )

    stairs = [
        StraightStairRequest(placement="left"),
        LTurnStairRequest(kind="l_turn", placement="left"),
        UTurnStairRequest(kind="u_turn", placement="left"),
        WinderTurnStairRequest(kind="winder_turn", placement="left"),
        SpiralStairRequest(kind="spiral", placement="left"),
    ]
    for stair in stairs:
        with pytest.raises(ValidationError, match="setback upper floor"):
            house(stair, y_min_mm=500)
        # The left-wall stair keeps its clearance when only the opposite wall is set back.
        plan = house(stair, y_max_mm=1_000).build()
        assert any(
            op.id == "stair_opening_2" or op.id.startswith("stair_opening_2_")
            for op in plan.operations
        )


def test_per_floor_setbacks_step_each_level_and_roof_repeats_top_floor() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=3,
        upper_floor_setbacks_mm=(
            UpperFloorSetbackSides(x_max_mm=2_000),
            UpperFloorSetbackSides(x_max_mm=4_000, y_min_mm=1_000),
        ),
    )
    plan = request.build()
    boxes = {op.id: op for op in plan.operations if isinstance(op, CreateBox)}
    assert boxes["floor_1"].origin_mm == (0.0, 0.0, 0.0)
    assert boxes["floor_2"].origin_mm == (0.0, 0.0, 3_000.0)
    assert (boxes["floor_2"].width_mm, boxes["floor_2"].depth_mm) == (10_000.0, 8_000.0)
    for body, z in (("floor_3", 6_000.0), ("roof", 9_000.0)):
        assert boxes[body].origin_mm == (0.0, 1_000.0, z)
        assert (boxes[body].width_mm, boxes[body].depth_mm) == (8_000.0, 7_000.0)
    assert "its own validated per-side setback" in " ".join(plan.assumptions)

    levels = floor_plans_from_house_box(
        request, project_id="project", version_id="version", name="House"
    ).levels
    assert levels[1].plan.rooms[0].outline == [
        (0.0, 0.0),
        (10_000.0, 0.0),
        (10_000.0, 8_000.0),
        (0.0, 8_000.0),
    ]
    assert levels[2].plan.rooms[0].outline == [
        (0.0, 1_000.0),
        (8_000.0, 1_000.0),
        (8_000.0, 8_000.0),
        (0.0, 8_000.0),
    ]

    # Equal levels describe the same geometry as the per-side field.
    sides = UpperFloorSetbackSides(x_min_mm=300, y_max_mm=700)
    per_side = replace(
        request, upper_floor_setbacks_mm=None, upper_floor_setback_sides_mm=sides
    ).build()
    per_floor = replace(request, upper_floor_setbacks_mm=(sides, sides)).build()
    assert per_floor.operations == per_side.operations

    # A job-input round trip (lists of dicts) rebuilds the same validated request.
    assert HouseBoxRequest(**json.loads(json.dumps(asdict(request)))) == request


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"upper_floor_setback_mm": 200}, "send only one"),
        ({"upper_floor_setback_sides_mm": {"x_min_mm": 100}}, "send only one"),
        ({"levels": [{"x_min_mm": 100}]}, "exactly one entry per upper floor"),
        ({"floors": 2, "levels": [{"x_min_mm": 100}] * 2}, "exactly one entry per upper floor"),
        ({"levels": [{}, {}]}, "at least one positive side"),
        ({"floors": 1, "levels": []}, "at least one positive side"),
        ({"shape": "l_shape"}, "rectangular house"),
        ({"levels": [{}, {"y_min_mm": 3_000, "y_max_mm": 3_001}]}, "at least 2000 mm"),
        ({"levels": [{"x_min_mm": 1_000}, {"x_min_mm": 500}]}, "no overhang"),
        ({"levels": [{}, {"x_min_mm": float("inf")}]}, "finite"),
        ({"levels": [{}, {"x_min_mm": float("nan")}]}, "finite"),
        ({"levels": [{}, {"x_min_mm": "100"}]}, "valid number"),
        ({"levels": [{}, {"x_min_mm": True}]}, "valid number"),
        ({"levels": [{}, {"front_mm": 100}]}, "front_mm"),
    ],
)
def test_invalid_per_floor_setbacks_fail_before_kernel(
    values: dict[str, Any], message: str
) -> None:
    levels = values.pop("levels", [{"x_min_mm": 100}, {"x_min_mm": 200}])
    request = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 3,
        **values,
        "upper_floor_setbacks_mm": levels,
    }
    with pytest.raises(ValidationError, match=message):
        HouseBoxRequest(**request)


def test_one_stair_must_fit_every_per_floor_setback() -> None:
    def house(stair: Any, *levels: UpperFloorSetbackSides) -> HouseBoxRequest:
        return HouseBoxRequest(
            length_mm=12_000,
            width_mm=8_000,
            floor_height_mm=3_000,
            floors=3,
            upper_floor_setbacks_mm=levels,
            stair=stair,
        )

    stairs = [
        StraightStairRequest(placement="left"),
        LTurnStairRequest(kind="l_turn", placement="left"),
        UTurnStairRequest(kind="u_turn", placement="left"),
        WinderTurnStairRequest(kind="winder_turn", placement="left"),
        SpiralStairRequest(kind="spiral", placement="left"),
    ]
    for stair in stairs:
        # Floor 2 alone would fit; the top floor steps back over the left-wall stair.
        with pytest.raises(ValidationError, match="setback upper floor"):
            house(
                stair,
                UpperFloorSetbackSides(y_max_mm=500),
                UpperFloorSetbackSides(y_min_mm=500, y_max_mm=500),
            )
        plan = house(
            stair, UpperFloorSetbackSides(y_max_mm=500), UpperFloorSetbackSides(y_max_mm=1_000)
        ).build()
        ids = {op.id for op in plan.operations}
        for floor in (2, 3):
            assert any(
                op_id == f"stair_opening_{floor}" or op_id.startswith(f"stair_opening_{floor}_")
                for op_id in ids
            )


def _spiral_request(house: dict[str, object] | None = None, **stair: object) -> HouseBoxRequest:
    values: dict[str, object] = {
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        **(house or {}),
    }
    return HouseBoxRequest(**values, stair=SpiralStairRequest(kind="spiral", **stair))  # type: ignore[arg-type]


@pytest.mark.parametrize("turn", ["left", "right"])
def test_spiral_stair_builds_exact_sector_treads_post_and_sector_opening(turn: str) -> None:
    request = _spiral_request(house={"floors": 3}, turn=turn)
    plan = request.build()
    assert len(plan.operations) == spiral_operation_count(request) == 73
    assert plan.expected_outputs == [
        "floor_1",
        "floor_2",
        "floor_3",
        "roof",
        "stair_1_2_step_1",
        "stair_2_3_step_1",
    ]
    layout = spiral_stair_layout(request)
    assert layout.center == (6_000.0, 4_000.0) and layout.rise == 200.0
    ops = {op.id: op for op in plan.operations}
    sign = 1 if turn == "left" else -1
    assert layout.angles_deg[1] == pytest.approx(sign * 20.0)
    for riser in range(1, 16):
        tread = ops[f"stair_2_3_step_{riser}"]
        assert tread.height_mm == pytest.approx(200.0 * riser)
        assert tread.origin_mm == (0.0, 0.0, 3_000.0)
        profile = tread.profile
        assert [segment.kind for segment in profile.segments] == ["line", "arc", "line"]
        # Every sector is counter-clockwise from its lower to its higher angle.
        low, high = layout.tread_bounds_deg(riser)
        assert profile.points_mm[1] == pytest.approx(layout.point(low))
        assert profile.points_mm[2] == pytest.approx(layout.point(high))
        assert high - low == pytest.approx(20.0)
        if riser > 1:
            assert ops[f"join_stair_2_3_step_{riser}"].target == "stair_2_3_step_1"
    assert ops["stair_1_2_post"].height_mm == 3_000.0
    assert ops["join_stair_1_2_post"].target == "stair_1_2_step_1"
    opening = ops["stair_opening_2"].profile
    low, high = layout.sweep_bounds_deg
    assert high - low == pytest.approx(300.0)
    assert opening.points_mm[0] == layout.center
    assert opening.points_mm[1] == pytest.approx(layout.point(low, 1_150.0))
    assert opening.points_mm[2] == pytest.approx(layout.point(high, 1_150.0))
    assert ops["cut_stair_opening_3"].target == "floor_3"
    assert "stair_opening_1" not in ops


def test_spiral_neighbouring_treads_share_bit_identical_riser_lines() -> None:
    request = _spiral_request(turn="right", step_count=16, sweep_deg=320.0)
    ops = {op.id: op for op in request.build().operations}
    for riser in range(1, 16):
        before = ops[f"stair_1_2_step_{riser}"].profile.points_mm
        after = ops[f"stair_1_2_step_{riser + 1}"].profile.points_mm
        assert len({tuple(p) for p in before} & {tuple(p) for p in after}) == 2


def test_spiral_floor_plans_share_outline_and_spiral_geometry() -> None:
    request = _spiral_request(house={"floors": 3}, turn="right", placement="left")
    floors = floor_plans_from_house_box(request, project_id="p", version_id="v", name="H")
    stairs = [stair for level in floors.levels for stair in level.plan.stairs]
    assert [stair.role for stair in stairs] == ["up", "down", "up", "down"]
    layout = spiral_stair_layout(request)
    for stair in stairs:
        assert stair.kind == "spiral" and stair.turn == "right" and not stair.railing
        assert stair.spiral is not None
        assert stair.spiral.center == layout.center == (6_000.0, 1_450.0)
        assert stair.spiral.radius_mm == 1_100.0 and stair.spiral.post_radius_mm == 100.0
        assert stair.spiral.sweep_deg == pytest.approx(300.0)
        assert len(stair.outline) == 24
        # The circumscribed outline contains the whole circle.
        assert min(math.dist(point, layout.center) for point in stair.outline) >= 1_100.0
        assert stair.width_mm == 1_000.0 and stair.tread_depth_mm == pytest.approx(209.44, 1e-3)
        assert stair.step_count == 15 and stair.riser_height_mm == 200.0
    assert stairs[0].outline == stairs[1].outline


@pytest.mark.parametrize(
    ("house", "stair", "message"),
    [
        ({}, {"step_count": 21}, "less than or equal to 20"),
        ({"floor_height_mm": 4_800}, {"step_count": 12}, "120-220 mm rise"),
        ({}, {"step_count": 15, "sweep_deg": 330.0, "diameter_mm": 3_200.0}, "clear tread width"),
        ({}, {"diameter_mm": 1_500.0}, "clear tread width"),
        ({}, {"sweep_deg": 180.0}, "walking line"),
        ({"floor_height_mm": 2_200}, {"step_count": 10, "sweep_deg": 330.0}, "tread angle"),
        (
            {"floor_height_mm": 2_400},
            {"step_count": 20, "sweep_deg": 330.0, "diameter_mm": 3_000.0, "post_diameter_mm": 300},
            "550-700",
        ),
        ({"width_mm": 2_899}, {}, "do not fit"),
        ({"length_mm": 2_899}, {}, "do not fit"),
        ({"width_mm": 2_900}, {}, None),
        ({"upper_floor_setback_mm": 2_700}, {}, "setback upper floor"),
        ({"floors": 1}, {}, "at least two floors"),
        ({"shape": "l_shape"}, {}, "rectangular house"),
    ],
)
def test_invalid_spiral_stairs_fail_before_kernel(
    house: dict[str, object], stair: dict[str, object], message: str | None
) -> None:
    if message is None:  # the exact 350 mm clearance boundary is accepted
        _spiral_request(house=house, **stair)
        return
    with pytest.raises(ValidationError, match=message):
        _spiral_request(house=house, **stair)


def test_spiral_request_is_strict_round_trips_and_rejects_railing() -> None:
    restored = HouseBoxRequest(**asdict(_spiral_request(turn="right", sweep_deg=315.0)))
    assert isinstance(restored.stair, SpiralStairRequest) and restored.stair.turn == "right"
    assert restored.build() == _spiral_request(turn="right", sweep_deg=315.0).build()
    base = {"length_mm": 12_000, "width_mm": 8_000, "floor_height_mm": 3_000, "floors": 2}
    for stair in (
        {"kind": "spiral", "railing": True},
        {"kind": "spiral", "diameter_mm": "2200"},
        {"kind": "spiral", "step_count": 15.0},
        {"kind": "spiral", "sweep_deg": float("nan")},
        {"kind": "spiral", "tread_depth_mm": 280},
        {"kind": "winder_turn", "sweep_deg": 300},
    ):
        with pytest.raises(ValidationError):
            HouseBoxRequest(**base, stair=stair)  # type: ignore[arg-type]


def test_maximum_spiral_stair_stays_within_operation_plan_limit() -> None:
    request = _spiral_request(
        house={"floors": 3, "floor_height_mm": 4_000},
        step_count=20,
        sweep_deg=330.0,
        diameter_mm=2_600.0,
        post_diameter_mm=200.0,
    )
    # 20 risers stays well inside the worker's 120-second kernel sandbox; 21 is rejected.
    assert len(request.build().operations) == spiral_operation_count(request) == 93
    with pytest.raises(ValidationError):
        _spiral_request(
            house={"floor_height_mm": 4_200},
            step_count=21,
            sweep_deg=330.0,
            diameter_mm=2_600.0,
            post_diameter_mm=200.0,
        )


@pytest.mark.skipif(not kernel.available(), reason="geometry-service binary is not installed")
@pytest.mark.parametrize("turn", ["left", "right"])
def test_real_kernel_fuses_each_spiral_flight_into_one_exact_solid(
    turn: str, tmp_path: Path
) -> None:
    request = _spiral_request(house={"floors": 3}, turn=turn)
    plan = request.build()
    result = kernel.execute_plan(plan.model_dump(mode="json"), tmp_path / "out")
    assert result.ok, result.error
    bodies = {body.name: body for body in result.bodies}
    assert set(plan.expected_outputs) <= set(bodies)
    layout = spiral_stair_layout(request)
    sector = math.pi * layout.radius**2 * 20.0 / 360.0
    post = math.pi * layout.post_radius**2
    # Treads are exact sectors; the post adds its part outside each tread's height.
    treads = sum(layout.rise * riser * sector for riser in range(1, 16))
    inside = sum((3_000.0 - layout.rise * riser) * post * 20.0 / 360.0 for riser in range(1, 16))
    outside = 3_000.0 * post * 60.0 / 360.0
    for name in ("stair_1_2_step_1", "stair_2_3_step_1"):
        assert bodies[name].solids == 1 and bodies[name].valid
        assert bodies[name].volume_mm3 == pytest.approx(treads + inside + outside, rel=1e-6)
    assert all(bodies[f"floor_{n}"].valid and bodies[f"floor_{n}"].solids == 1 for n in (1, 2, 3))
