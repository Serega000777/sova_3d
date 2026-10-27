"""T-160 (F-024/F-011): recognized profiles become a safe, editable plan."""

import pytest
from worker.features import (
    Band,
    Cylinder,
    EdgeFeature,
    FeatureReport,
    Loop,
    Pattern,
    Reconstruction,
    Thread,
)

from app.api.errors import ValidationFailedError
from app.services.reverse_engineering import durable_restoration_evidence, plan_from_report


def test_restoration_evidence_is_stable_for_job_and_immutable_version() -> None:
    restoration, reinforcement = durable_restoration_evidence("x_max", 20)
    assert restoration == {
        "mode": "mirrored_missing_half",
        "boundary": "x_max",
        "requires_physical_validation": True,
    }
    assert reinforcement == {
        "mode": "thickness_percent",
        "percent": 20,
        "datum": "minimum_z",
        "certified": False,
        "requires_physical_validation": True,
    }
    assert durable_restoration_evidence(None, None) == (None, None)


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


def test_one_standard_internal_thread_replaces_the_smooth_hole() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    cylinder = Cylinder(
        kind="hole",
        axis="z",
        centre_mm=(12.0, 20.0, 0.0),
        diameter_mm=5.5,
        length_mm=8.0,
        through=True,
        from_face="+",
        confidence=1.0,
    )
    report = FeatureReport(
        ok=True,
        cylinders=[cylinder],
        threads=[
            Thread(
                on="hole",
                axis="z",
                centre_mm=cylinder.centre_mm,
                major_diameter_mm=6.0,
                minor_diameter_mm=5.0,
                pitch_mm=1.0,
                designation="M6x1",
                confidence=0.9,
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

    assert [operation.type for operation in plan.operations] == [
        "extrude",
        "add_internal_thread",
    ]
    thread = plan.operations[-1].model_dump(mode="json")
    assert thread["major_diameter_mm"] == 6.0
    assert thread["minor_diameter_mm"] == 5.0
    assert thread["pitch_mm"] == 1.0
    assert thread["depth_mm"] is None


def test_low_confidence_or_nonstandard_thread_remains_a_smooth_hole() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    cylinder = Cylinder(
        kind="hole",
        axis="z",
        centre_mm=(12.0, 20.0, 0.0),
        diameter_mm=5.5,
        length_mm=8.0,
        through=True,
        from_face="+",
        confidence=1.0,
    )
    report = FeatureReport(
        ok=True,
        cylinders=[cylinder],
        threads=[
            Thread(
                on="hole",
                axis="z",
                centre_mm=cylinder.centre_mm,
                major_diameter_mm=6.0,
                minor_diameter_mm=5.0,
                pitch_mm=1.0,
                designation=None,
                confidence=0.5,
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

    assert [operation.type for operation in plan_from_report(report).operations] == [
        "extrude",
        "add_hole",
    ]


@pytest.mark.parametrize(
    ("pattern", "centres", "expected"),
    [
        (
            Pattern(
                kind="linear",
                count=3,
                diameter_mm=4,
                pitch_mm=10,
                angle_deg=30,
                centre_mm=(30, 20),
            ),
            [(21.34, 15), (30, 20), (38.66, 25)],
            {"kind": "linear", "count": 3, "pitch_mm": 10.0, "angle_deg": 30.0},
        ),
        (
            Pattern(
                kind="grid",
                count=4,
                diameter_mm=4,
                centre_mm=(30, 20),
                columns=2,
                rows=2,
                pitch_x_mm=20,
                pitch_y_mm=10,
            ),
            [(20, 15), (40, 15), (20, 25), (40, 25)],
            {
                "kind": "grid",
                "columns": 2,
                "rows": 2,
                "pitch_x_mm": 20.0,
                "pitch_y_mm": 10.0,
            },
        ),
        (
            Pattern(
                kind="circular",
                count=4,
                diameter_mm=4,
                pitch_deg=90,
                centre_mm=(30, 20),
                radius_mm=10,
                start_angle_deg=0,
            ),
            [(40, 20), (30, 30), (20, 20), (30, 10)],
            {"kind": "circular", "count": 4, "radius_mm": 10.0, "start_angle_deg": 0.0},
        ),
    ],
)
def test_recognized_hole_pattern_becomes_one_parametric_operation(
    pattern: Pattern,
    centres: list[tuple[float, float]],
    expected: dict[str, object],
) -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    cylinders = [
        Cylinder(
            kind="hole",
            axis="z",
            centre_mm=(x, y, 0),
            diameter_mm=4,
            length_mm=8,
            through=True,
            from_face="+",
            confidence=1,
        )
        for x, y in centres
    ]
    report = FeatureReport(
        ok=True,
        cylinders=cylinders,
        patterns=[pattern],
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(60, 40, 8),
            bands=[Band(z0_mm=0, z1_mm=8, outer=[outline], holes=[], levels=24)],
            fidelity="prismatic",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report)

    assert [operation.type for operation in plan.operations] == ["extrude", "add_hole_pattern"]
    operation = plan.operations[-1].model_dump(mode="json")
    assert operation["centre_mm"] == [30.0, 20.0]
    assert operation["diameter_mm"] == 4.0
    assert operation["pattern"] == expected


@pytest.mark.parametrize(
    ("outline_update", "operation_type", "size_field", "size_mm"),
    [
        ({"corner_radius_mm": 3.0}, "fillet", "radius_mm", 3.0),
        ({"chamfer_mm": 2.0}, "chamfer", "distance_mm", 2.0),
    ],
)
def test_a_measured_rectangle_edge_treatment_is_replayed_exactly(
    outline_update: dict[str, float],
    operation_type: str,
    size_field: str,
    size_mm: float,
) -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    ).model_copy(update=outline_update)
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

    plan = plan_from_report(report)

    assert [operation.type for operation in plan.operations] == ["extrude", operation_type]
    treatment = plan.operations[-1].model_dump(mode="json")
    assert treatment["target"] == "rebuild_1"
    assert treatment["edges"] == {
        "kind": "edges_parallel_to",
        "axis": "z",
        "outer": True,
    }
    assert treatment[size_field] == size_mm


def test_ambiguous_multi_band_edge_treatments_remain_report_only() -> None:
    rounded = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
        corner_radius_mm=3.0,
    )
    report = FeatureReport(
        ok=True,
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(60.0, 40.0, 16.0),
            bands=[
                Band(z0_mm=0.0, z1_mm=8.0, outer=[rounded], holes=[], levels=12),
                Band(z0_mm=8.0, z1_mm=16.0, outer=[rounded], holes=[], levels=12),
            ],
            fidelity="stepped",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report)

    assert "fillet" not in [operation.type for operation in plan.operations]


@pytest.mark.parametrize(
    ("where", "kind", "size_field", "size_mm", "sign"),
    [
        ("top", "fillet", "radius_mm", 2.5, "+"),
        ("bottom", "chamfer", "distance_mm", 1.5, "-"),
    ],
)
def test_a_measured_end_edge_treatment_is_replayed_exactly(
    where: str,
    kind: str,
    size_field: str,
    size_mm: float,
    sign: str,
) -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    end_edge = EdgeFeature(kind=kind, where=where, size_mm=size_mm, count=4)
    reconstruction = Reconstruction(
        frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        extents_mm=(60.0, 40.0, 8.0),
        bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[], levels=24)],
        top_edge=end_edge if where == "top" else None,
        bottom_edge=end_edge if where == "bottom" else None,
        fidelity="prismatic",
        levels=24,
        unexplained_levels=0,
    )

    plan = plan_from_report(FeatureReport(ok=True, reconstruction=reconstruction))

    assert [operation.type for operation in plan.operations] == ["extrude", kind]
    treatment = plan.operations[-1].model_dump(mode="json")
    assert treatment["edges"] == {
        "kind": "edges_of_face",
        "face": {"kind": "face_by_normal", "axis": "z", "sign": sign},
    }
    assert treatment[size_field] == size_mm


def test_an_end_treatment_with_a_hole_remains_report_only() -> None:
    outline = Loop(
        kind="rectangle",
        centre_mm=(30.0, 20.0),
        area_mm2=2400.0,
        width_mm=60.0,
        depth_mm=40.0,
    )
    hole = Loop(
        kind="circle",
        centre_mm=(30.0, 20.0),
        area_mm2=19.63,
        diameter_mm=5.0,
    )
    report = FeatureReport(
        ok=True,
        reconstruction=Reconstruction(
            frame_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            extents_mm=(60.0, 40.0, 8.0),
            bands=[Band(z0_mm=0.0, z1_mm=8.0, outer=[outline], holes=[hole], levels=24)],
            top_edge=EdgeFeature(kind="fillet", where="top", size_mm=2.0, count=4),
            fidelity="prismatic",
            levels=24,
            unexplained_levels=0,
        ),
    )

    plan = plan_from_report(report)

    assert [operation.type for operation in plan.operations] == ["extrude"]


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
