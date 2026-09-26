"""F-019 and F-001 end-to-end proof: the real Shap-E pipeline, not mocked (`test_reconstruction.py`
covers frame selection, rescaling and error handling against a fake sandbox).

Opt-in only: CPU inference takes on the order of 15-30 minutes and downloads ~2.4 GB of
model checkpoints on first use. Enable explicitly:

    SOVA_RUN_SHAP_E_LIVE=1 uv run pytest tests/test_reconstruct_photo_live.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import trimesh

from worker.reconstruction import Frame, ScanInput, reconstructor_for

pytestmark = pytest.mark.skipif(
    not os.environ.get("SOVA_RUN_SHAP_E_LIVE"),
    reason=(
        "real Shap-E inference is slow (15-30 min CPU) and downloads ~2.4 GB on first run; "
        "set SOVA_RUN_SHAP_E_LIVE=1 to run it"
    ),
)


def _synthetic_photo(path: Path) -> None:
    """Any valid image proves the pipeline; a real product photo is not the point here."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (256, 256), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.ellipse((48, 48, 208, 208), fill=(200, 60, 40))
    image.save(path)


def test_a_photo_becomes_a_real_solid_mesh(tmp_path: Path) -> None:
    photo = tmp_path / "sample.png"
    _synthetic_photo(photo)
    scan = ScanInput(frames=(Frame(0, photo, "rgb"),), scale_hint_mm=80.0, scale_confidence=0.9)

    result = reconstructor_for("shap_e").reconstruct(scan, tmp_path / "out")

    assert result.provider == "shap_e"
    mesh = trimesh.load(result.mesh_path, force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert len(mesh.vertices) > 0 and len(mesh.faces) > 0
    assert max(mesh.extents) == pytest.approx(80.0, rel=1e-2)
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_a_prompt_becomes_a_real_solid_mesh(tmp_path: Path) -> None:
    from worker.generate_mesh import generate_from_text

    result = generate_from_text("a small owl figurine", 60.0, tmp_path / "text")

    mesh = trimesh.load(result.mesh_path, force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert len(mesh.faces) > 100
    assert max(mesh.extents) == pytest.approx(60.0, rel=1e-2)
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6)
