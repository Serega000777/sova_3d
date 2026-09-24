"""Real slicing (F-054, second stage): perimeters, infill and G-code."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import trimesh

from worker.gcode import FILAMENT_DIAMETER_MM, SliceSettings, slice_file_in_sandbox, slice_mesh
from worker.printcheck import PrinterProfile


def _filament_area_mm2() -> float:
    r = FILAMENT_DIAMETER_MM / 2
    return math.pi * r * r


def test_full_density_extrudes_the_mesh_volume() -> None:
    """At 100% infill the deposited volume must match the box, whatever wall_count is."""
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    for walls in (1, 3):
        _, stats = slice_mesh(
            mesh, printer, SliceSettings(infill_density_pct=100, wall_count=walls, skirt=False)
        )
        deposited_mm3 = stats.filament_used_mm * _filament_area_mm2()
        assert deposited_mm3 == pytest.approx(mesh.volume, rel=0.03)
    assert stats.total_layers == 50


def test_lower_density_uses_less_filament_than_full() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, sparse = slice_mesh(mesh, printer, SliceSettings(infill_density_pct=10, skirt=False))
    _, dense = slice_mesh(mesh, printer, SliceSettings(infill_density_pct=100, skirt=False))
    assert 0 < sparse.filament_used_mm < dense.filament_used_mm


def test_more_walls_use_more_filament_at_zero_infill() -> None:
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    _, one_wall = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=0, wall_count=1, skirt=False)
    )
    _, three_walls = slice_mesh(
        mesh, printer, SliceSettings(infill_density_pct=0, wall_count=3, skirt=False)
    )
    assert one_wall.filament_used_mm < three_walls.filament_used_mm


def test_a_ring_keeps_its_hole_open() -> None:
    outer = trimesh.creation.box(extents=(30, 30, 6))
    inner = trimesh.creation.cylinder(radius=8, height=20)
    ring = outer.difference(inner, engine="manifold")
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4)
    text, stats = slice_mesh(ring, printer, SliceSettings(infill_density_pct=100, skirt=False))
    deposited_mm3 = stats.filament_used_mm * _filament_area_mm2()
    assert deposited_mm3 == pytest.approx(ring.volume, rel=0.05)
    # a solid box of the same footprint would need noticeably more filament
    solid_text, solid_stats = slice_mesh(
        outer, printer, SliceSettings(infill_density_pct=100, skirt=False)
    )
    assert stats.filament_used_mm < solid_stats.filament_used_mm


def test_gcode_is_well_formed() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    printer = PrinterProfile(layer_height_mm=0.2, nozzle_mm=0.4)
    text, stats = slice_mesh(mesh, printer, SliceSettings())
    lines = text.splitlines()
    assert lines[-1] == "M84"
    assert "M104 S0" in lines and "M140 S0" in lines
    assert any(line.startswith("M109") for line in lines)  # waits for nozzle temp
    assert any(line.startswith("M190") for line in lines)  # waits for bed temp
    body = text.split("G91", 1)[0]  # the footer's relative Z-lift comes after this
    z_values = [float(m.group(1)) for m in re.finditer(r"^G1 Z([\d.]+)", body, re.MULTILINE)]
    assert z_values == sorted(z_values)
    assert z_values[-1] == pytest.approx(stats.total_layers * printer.layer_height_mm)
    for match in re.finditer(r"E(-?[\d.]+)", text):
        # relative extrusion mode (M83): every E value is a finite, bounded move
        assert abs(float(match.group(1))) < 50


def test_rejects_non_fdm_and_non_watertight() -> None:
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    with pytest.raises(ValueError, match="FDM"):
        slice_mesh(mesh, PrinterProfile(technology="resin"), SliceSettings())
    open_mesh = trimesh.creation.box(extents=(10, 10, 2))
    open_mesh.update_faces(open_mesh.face_normals[:, 0] < 0.5)
    with pytest.raises(ValueError, match="closed solid"):
        slice_mesh(open_mesh, PrinterProfile(), SliceSettings())


def test_supports_add_material_under_a_real_overhang() -> None:
    # a T-bridge: a wide top slab on a narrow leg, so the slab's underside overhangs air
    leg = trimesh.creation.box(extents=(6, 6, 20))
    leg.apply_translation((0, 0, 10))
    slab = trimesh.creation.box(extents=(30, 30, 4))
    slab.apply_translation((0, 0, 22))
    bridge = trimesh.util.concatenate([leg, slab])
    assert isinstance(bridge, trimesh.Trimesh)
    bridge = trimesh.Trimesh(bridge.vertices, bridge.faces).process(validate=True)
    assert bridge.is_watertight
    printer = PrinterProfile(layer_height_mm=0.3, nozzle_mm=0.4, max_overhang_deg=45)
    _, without = slice_mesh(
        bridge, printer, SliceSettings(infill_density_pct=10, supports=False, skirt=False)
    )
    _, with_supports = slice_mesh(
        bridge, printer, SliceSettings(infill_density_pct=10, supports=True, skirt=False)
    )
    assert with_supports.support_columns > 0
    assert with_supports.filament_used_mm > without.filament_used_mm


def test_sandbox_slice_writes_a_real_gcode_file(tmp_path: Path) -> None:
    mesh_path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(8, 8, 2)).export(mesh_path)
    out_dir = tmp_path / "out"
    stats = slice_file_in_sandbox(mesh_path, PrinterProfile(), SliceSettings(), out_dir)
    gcode_path = out_dir / stats["gcode_file"]
    assert gcode_path.exists()
    assert gcode_path.stat().st_size == stats["gcode_bytes"]
    import hashlib

    assert hashlib.sha256(gcode_path.read_bytes()).hexdigest() == stats["gcode_sha256"]
