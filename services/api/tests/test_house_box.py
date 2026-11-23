"""The house quick-start is a validated, deterministic operation plan."""

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from app.engineering.floor_plan import PlanStair, floor_plans_from_house_box
from app.engineering.house_box import (
    HouseBoxRequest,
    LTurnStairRequest,
    StraightStairRequest,
    l_stair_layout,
    l_stair_rail_ids,
)
from app.geometry.operations import CreateBox


def test_rectangle_builds_one_box_with_total_floor_height() -> None:
    plan = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        shape="rectangle",
    ).build()

    assert plan.expected_outputs == ["house"]
    assert [op.type for op in plan.operations] == ["create_box"]
    box = plan.operations[0]
    assert (box.width_mm, box.depth_mm, box.height_mm) == (12_000, 8_000, 6_000)


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
            stair={"kind": "spiral"},  # type: ignore[arg-type]
        )
