from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
import trimesh

from worker.mechanisms import build_hinged_lid, build_sliding_lid, sliding_lid_layout


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


SLIDING = {
    "width_mm": 100,
    "depth_mm": 70,
    "base_height_mm": 30,
    "wall_mm": 3,
    "floor_mm": 2,
    "lid_thickness_mm": 3,
    "guide_width_mm": 1.5,
    "lip_overhang_mm": 2.5,
    "lip_thickness_mm": 1.5,
    "clearance_mm": 0.3,
}


def _placed_lid(lid: trimesh.Trimesh, travel_mm: float) -> trimesh.Trimesh:
    layout = sliding_lid_layout(**SLIDING)
    moved = lid.copy()
    moved.apply_translation([0, layout["lid_y_mm"] + travel_mm, layout["lid_z_mm"]])
    return moved


def test_sliding_lid_has_two_watertight_parts_with_explicit_guides() -> None:
    parts = build_sliding_lid(**SLIDING)
    assert set(parts) == {"base", "lid"}
    base, lid = load(parts["base"]), load(parts["lid"])
    assert base.is_watertight and lid.is_watertight
    assert len(base.split()) == len(lid.split()) == 1
    # base: 3 mm walls to 30 mm, channel 30..33.3, lips 33.3..34.8
    np.testing.assert_allclose(base.bounds, [[-50.0, 0.0, 0.0], [50.0, 70.0, 34.8]], atol=1e-4)
    # lid: 100 - 2 * (1.5 guide + 0.3 clearance) wide, 70 - 3 back wall - 0.3 deep
    np.testing.assert_allclose(lid.bounds, [[-48.2, 0.0, 0.0], [48.2, 66.7, 3.0]], atol=1e-4)
    # the open box holds volume: far less than its solid bounding box
    assert base.volume < 0.5 * float(np.prod(base.extents))


@pytest.mark.parametrize("travel", [0.0, 30.0, 66.7])
def test_sliding_lid_clears_the_guides_along_its_travel(travel: float) -> None:
    parts = build_sliding_lid(**SLIDING)
    base, lid = load(parts["base"]), _placed_lid(load(parts["lid"]), travel)
    overlap = trimesh.boolean.intersection([base, lid], engine="manifold")
    assert overlap.is_empty or overlap.volume < 1e-6
    # the lid sits on the wall tops and stays 0.3 mm under the lips and beside the risers
    assert lid.bounds[0][2] == pytest.approx(30, abs=1e-4)
    assert 33.3 - lid.bounds[1][2] == pytest.approx(0.3, abs=1e-4)
    assert 50 - 1.5 - lid.bounds[1][0] == pytest.approx(0.3, abs=1e-4)


def test_sliding_lid_is_retained_under_the_lips_and_bears_on_the_walls() -> None:
    layout = sliding_lid_layout(**SLIDING)
    lid_half = layout["lid_width_mm"] / 2
    assert lid_half - layout["lip_inner_x_mm"] == pytest.approx(layout["retention_mm"])
    assert layout["retention_mm"] == pytest.approx(2.2)
    assert lid_half - (50 - 3) == pytest.approx(layout["bearing_mm"])
    assert layout["bearing_mm"] == pytest.approx(1.2)
    # a closed lid touches nothing but its seat: back stop is clearance_mm behind it
    assert layout["lid_y_mm"] - 3 == pytest.approx(0.3)
    # lifting the lid past its clearance drives it into the lips: they really retain it
    parts = build_sliding_lid(**SLIDING)
    lifted = _placed_lid(load(parts["lid"]), 10)
    lifted.apply_translation([0, 0, 1.0])
    hit = trimesh.boolean.intersection([load(parts["base"]), lifted], engine="manifold")
    assert hit.volume > 1


@pytest.mark.parametrize(
    "change,message",
    [
        ({"guide_width_mm": 2.8}, "bear on the side walls"),
        ({"lip_overhang_mm": 0.5}, "retain"),
        ({"floor_mm": 29.5}, "floor"),
        ({"wall_mm": 49}, "cavity"),
        ({"clearance_mm": float("nan")}, "finite"),
        ({"width_mm": -1}, "positive"),
    ],
)
def test_sliding_lid_rejects_unbuildable_dimensions(change: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_sliding_lid(**{**SLIDING, **change})
