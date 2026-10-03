"""The house quick-start is a validated, deterministic operation plan."""

import pytest
from pydantic import ValidationError

from app.engineering.house_box import HouseBoxRequest


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


@pytest.mark.parametrize(
    ("shape", "boxes", "unions"), [("l_shape", 2, 1), ("t_shape", 3, 2)]
)
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
