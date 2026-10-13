"""The house quick-start is a validated, deterministic operation plan."""

import pytest
from pydantic import ValidationError

from app.engineering.floor_plan import floor_plans_from_house_box
from app.engineering.house_box import HouseBoxRequest, StraightStairRequest
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
