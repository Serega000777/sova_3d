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


def test_sphere_and_cone_primitive_plans_have_exact_dimensions() -> None:
    sphere = primitive_plan(kind="sphere", diameter_mm=24).operations[0]
    assert sphere.type == "create_sphere" and sphere.diameter_mm == 24
    cone = primitive_plan(
        kind="cone", diameter_mm=30, top_diameter_mm=10, height_mm=40
    ).operations[0]
    assert cone.type == "create_cone"
    assert cone.bottom_diameter_mm == 30
    assert cone.top_diameter_mm == 10
    assert cone.height_mm == 40
