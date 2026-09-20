"""T-159 (F-024): a plain manufactured part is read back as editable structure."""

import pytest
import trimesh

from worker.features import FeatureRequest, recognize


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
