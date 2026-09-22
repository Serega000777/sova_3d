"""Geometric layer preview: dimensions and contours must match the actual mesh."""

from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from worker.printcheck import PrinterProfile
from worker.slicing import preview, preview_file


def test_box_slices_have_real_contours_at_profile_height() -> None:
    mesh = trimesh.creation.box(extents=(20, 10, 4))
    result = preview(mesh, PrinterProfile(layer_height_mm=0.2))
    assert result["total_layers"] == 20
    assert len(result["sampled_layers"]) == 20
    assert result["bounds_mm"] == [20.0, 10.0, 4.0]
    first = result["sampled_layers"][0]
    assert first["z_mm"] == 0.1
    assert first["paths"] and first["paths"][0][0] == first["paths"][0][-1]
    assert result["preview_only"] is True


def test_preview_rejects_open_mesh_and_out_of_bed() -> None:
    mesh = trimesh.creation.box(extents=(20, 10, 4))
    mesh.update_faces(mesh.face_normals[:, 0] < 0.5)
    with pytest.raises(ValueError, match="closed solid"):
        preview(mesh, PrinterProfile())
    with pytest.raises(ValueError, match="exceeds the printer bed"):
        preview(trimesh.creation.box(extents=(300, 270, 4)), PrinterProfile())


def test_sandbox_preview(tmp_path: Path) -> None:
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(8, 6, 2)).export(path)
    result = preview_file(path, PrinterProfile())
    assert result["total_layers"] == 10
