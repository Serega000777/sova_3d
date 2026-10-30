"""T-159 (F-024): a plain manufactured part is read back as editable structure."""

import pytest
import trimesh

from worker.features import Cylinder, FeatureRequest, _patterns, recognize


def test_box_is_recognized_as_one_prismatic_band() -> None:
    mesh = trimesh.creation.box(extents=(60.0, 40.0, 8.0))

    report = recognize(
        mesh,
        FeatureRequest(tolerance_mm=0.2, max_levels=24, samples=300, threads=False),
    )

    assert report.ok
    assert report.reconstruction is not None
    assert report.reconstruction.fidelity == "prismatic"
    assert len(report.reconstruction.bands) == 1
    band = report.reconstruction.bands[0]
    assert band.z1_mm - band.z0_mm == pytest.approx(report.reconstruction.extents_mm[2], abs=0.3)
    assert band.outer[0].kind == "rectangle"
    assert sorted(report.extents_mm) == pytest.approx([8.0, 40.0, 60.0], abs=0.2)


def _hole(x: float, y: float) -> Cylinder:
    return Cylinder(
        kind="hole",
        axis="z",
        centre_mm=(x, y, 0),
        diameter_mm=4,
        length_mm=8,
        through=True,
        confidence=1,
    )


def test_pattern_recognition_retains_linear_and_circular_phase() -> None:
    linear = _patterns([_hole(10, 10), _hole(20, 20), _hole(30, 30)], 0.05)
    assert len(linear) == 1 and linear[0].kind == "linear"
    assert linear[0].angle_deg == pytest.approx(45)
    assert linear[0].pitch_mm == pytest.approx(2**0.5 * 10, abs=0.001)

    circular = _patterns([_hole(30, 20), _hole(20, 30), _hole(10, 20), _hole(20, 10)], 0.05)
    assert len(circular) == 1 and circular[0].kind == "circular"
    assert circular[0].start_angle_deg == pytest.approx(-90)
    assert circular[0].radius_mm == pytest.approx(10)
