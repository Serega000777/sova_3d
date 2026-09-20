"""T-173 (F-061): manual primitives are ordinary validated operation plans."""

from app.services.modeling import primitive_plan


def test_box_primitive_plan_has_exact_dimensions() -> None:
    plan = primitive_plan(kind="box", width_mm=80, depth_mm=60, height_mm=40)
    operation = plan.operations[0]
    assert operation.type == "create_box"
    assert operation.width_mm == 80
    assert operation.depth_mm == 60
    assert operation.height_mm == 40
    assert plan.expected_outputs == ["body"]


def test_cylinder_primitive_plan_has_exact_dimensions() -> None:
    plan = primitive_plan(kind="cylinder", diameter_mm=32, height_mm=70)
    operation = plan.operations[0]
    assert operation.type == "create_cylinder"
    assert operation.diameter_mm == 32
    assert operation.height_mm == 70
