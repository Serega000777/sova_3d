"""T-160 (F-024/F-011): recognized profiles become a safe, editable plan."""

from worker.features import Band, Cylinder, FeatureReport, Loop, Reconstruction

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
