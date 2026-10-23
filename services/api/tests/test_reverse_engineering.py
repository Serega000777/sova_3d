"""T-160 (F-024/F-011): recognized profiles become a safe, editable plan."""

import pytest
from worker.features import Band, Cylinder, FeatureReport, Loop, Reconstruction

from app.api.errors import ValidationFailedError
from app.services.reverse_engineering import plan_from_report


def test_recognized_plate_and_hole_become_parametric_operations() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    report = FeatureReport(
        ok=True,
        cylinders=[
            Cylinder(
                kind="hole",
                axis="z",
                centre_mm=(12.0, 20.0, 0.0),
                diameter_mm=5.5,
                length_mm=8.0,
                through=True,
                from_face="+",
                confidence=1.0,
            )
        ],
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(60.0, 40.0, 8.0),
            bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[], levels=24)],
            fidelity="prismatic",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report)

    assert plan.expected_outputs == ["rebuild_1"]
    assert [operation.type for operation in plan.operations] == ["extrude", "add_hole"]
    extrusion = plan.operations[0].model_dump()
    assert extrusion["origin_mm"] == (0.0, 0.0, 0.0)
    hole = plan.operations[1].model_dump()
    assert hole["target"] == "rebuild_1"
    assert hole["position_mm"] == (12.0, 20.0)
    assert hole["diameter_mm"] == 5.5


def test_a_prismatic_replacement_can_be_thickened_from_its_datum() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    report = FeatureReport(
        ok=True,
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(60.0, 40.0, 8.0),
            bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[], levels=24)],
            fidelity="prismatic",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report, reinforce_thickness_percent=25)

    assert [operation.type for operation in plan.operations] == ["extrude", "set_dimensions"]
    assert plan.operations[-1].model_dump()["height_mm"] == 10.0
    assert "not a certified load calculation" in plan.assumptions[-1]


def test_reinforcement_refuses_a_side_hole_or_same_axis_restoration() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    side_hole = Cylinder(
        kind="hole",
        axis="x",
        centre_mm=(0.0, 20.0, 4.0),
        diameter_mm=4.0,
        length_mm=60.0,
        through=True,
        from_face="+",
        confidence=1.0,
    )
    reconstruction = Reconstruction(
        frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        extents_mm=(60.0, 40.0, 8.0),
        bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[], levels=24)],
        side_holes=[side_hole],
        fidelity="prismatic",
        levels=24,
        unexplained_levels=0,
    )
    with pytest.raises(ValidationFailedError, match="side hole"):
        plan_from_report(
            FeatureReport(ok=True, reconstruction=reconstruction),
            reinforce_thickness_percent=20,
        )
    with pytest.raises(ValidationFailedError, match="restoration axis"):
        plan_from_report(
            FeatureReport(
                ok=True,
                reconstruction=reconstruction.model_copy(update={"side_holes": []}),
            ),
            restore_missing_half="z_max",
            reinforce_thickness_percent=20,
        )


def test_a_declared_missing_symmetric_half_is_mirrored_and_fused() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(15.0, 20.0),
        area_mm2=1200.0,
        width_mm=30.0,
        depth_mm=40.0,
    )
    report = FeatureReport(
        ok=True,
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(30.0, 40.0, 8.0),
            bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[], levels=24)],
            fidelity="prismatic",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report, restore_missing_half="x_max")

    assert [operation.type for operation in plan.operations] == ["extrude", "mirror"]
    mirrored = plan.operations[1].model_dump()
    assert mirrored["axis"] == "x"
    assert mirrored["offset_mm"] == 30.0
    assert mirrored["keep_original"] is True
    assert mirrored["target"] == "rebuild_1"
    assert plan.expected_outputs == ["rebuild_1"]
