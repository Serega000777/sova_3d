from __future__ import annotations

from io import BytesIO

import pytest
import trimesh

from worker.mechanisms import build_hinged_lid


def load(data: bytes) -> trimesh.Trimesh:
    mesh = trimesh.load(BytesIO(data), file_type="stl", force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    return mesh


def test_hinged_lid_has_three_metric_printable_parts() -> None:
    parts = build_hinged_lid(
        width_mm=100,
        depth_mm=70,
        base_height_mm=18,
        lid_thickness_mm=4,
        pin_diameter_mm=4,
        clearance_mm=0.3,
    )
    assert set(parts) == {"base", "lid", "pin"}
    base, lid, pin = (load(parts[name]) for name in ("base", "lid", "pin"))
    assert base.is_watertight and lid.is_watertight and pin.is_watertight
    assert len(base.split()) == len(lid.split()) == len(pin.split()) == 1
    assert base.bounds[1].tolist() == pytest.approx([50, 70, 21.5])
    assert lid.bounds[1].tolist() == pytest.approx([50, 70, 4])
    assert pin.extents.tolist() == pytest.approx([102, 4, 4])


def test_hinged_lid_rejects_a_base_that_cannot_contain_the_hinge() -> None:
    with pytest.raises(ValueError, match="base height"):
        build_hinged_lid(
            width_mm=100,
            depth_mm=70,
            base_height_mm=3,
            lid_thickness_mm=4,
            pin_diameter_mm=8,
            clearance_mm=0.3,
        )
