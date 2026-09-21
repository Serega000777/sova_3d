"""T-173 (F-061): manual primitives are ordinary validated operation plans."""

from app.services.modeling import primitive_plan


def test_box_primitive_plan_has_exact_dimensions() -> None:
    plan = primitive_plan(kind="box", width_mm=80, depth_mm=60, height_mm=40)
    operation = plan.operations[0]
    assert operation.type == "create_box"
    assert operation.width_mm == 80
    assert operation.depth_mm == 60
    assert operation.height_mm == 40
    assert operation.centered is True
    assert plan.expected_outputs == ["body"]


def test_cylinder_primitive_plan_has_exact_dimensions() -> None:
    plan = primitive_plan(kind="cylinder", diameter_mm=32, height_mm=70)
    operation = plan.operations[0]
    assert operation.type == "create_cylinder"
    assert operation.diameter_mm == 32
    assert operation.height_mm == 70
    assert operation.origin_mm == (0.0, 0.0, -35.0)


def test_sphere_and_cone_primitive_plans_have_exact_dimensions() -> None:
    sphere = primitive_plan(kind="sphere", diameter_mm=24).operations[0]
    assert sphere.type == "create_sphere" and sphere.diameter_mm == 24
    cone = primitive_plan(kind="cone", diameter_mm=30, top_diameter_mm=10, height_mm=40).operations[
        0
    ]
    assert cone.type == "create_cone"
    assert cone.bottom_diameter_mm == 30
    assert cone.top_diameter_mm == 10
    assert cone.height_mm == 40


def test_axial_primitive_can_use_an_axis_and_its_base_as_origin() -> None:
    cylinder = primitive_plan(
        kind="cylinder", diameter_mm=12, height_mm=30, axis="x", centered=False
    ).operations[0]
    assert cylinder.axis == "x"
    assert cylinder.origin_mm == (0.0, 0.0, 0.0)

    cone = primitive_plan(
        kind="cone", diameter_mm=20, height_mm=10, axis="y", centered=True
    ).operations[0]
    assert cone.axis == "y"
    assert cone.origin_mm == (0.0, -5.0, 0.0)


def test_torus_plan_uses_outer_and_tube_diameters() -> None:
    ring = primitive_plan(
        kind="torus", outer_diameter_mm=40, tube_diameter_mm=8, axis="x"
    ).operations[0]
    assert ring.type == "create_torus"
    assert ring.outer_diameter_mm == 40
    assert ring.tube_diameter_mm == 8
    assert ring.axis == "x"
