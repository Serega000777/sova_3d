"""T-022: STEP/IGES arrive as B-Rep and come back as bodies with a bounding box in mm.

Skipped unless the OCCT binary is on PATH — the worker image has it, and so does the
containerized CI job, which is where this contract actually matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worker import geometry, importers
from worker.importers.cad import import_cad

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.skipif(not geometry.available(), reason="geometry-service binary missing")


@pytest.mark.parametrize(("name", "format_id"), [("box.step", "step"), ("box.iges", "iges")])
def test_cad_file_loads_as_a_solid_in_millimetres(name: str, format_id: str) -> None:
    result = import_cad(FIXTURES / name, format_id)
    assert result.ok, result.error
    meta = result.metadata
    assert meta is not None
    assert meta.units == "mm" and meta.unit_source == "file"
    assert meta.bbox is not None
    assert tuple(round(v, 4) for v in meta.bbox.size) == (30.0, 20.0, 10.0)
    assert meta.mesh is not None
    assert meta.mesh.bodies == 1 and meta.mesh.watertight
    assert meta.mesh.volume_mm3 == pytest.approx(6000.0, rel=1e-4)
    assert meta.mesh.surface_area_mm2 == pytest.approx(2200.0, rel=1e-4)
    assert meta.parser.startswith("geometry-service/")
    assert not [w for w in meta.warnings if w.severity == "error"]


def test_the_converted_bodies_can_be_kept(tmp_path: Path) -> None:
    """The platform stores what the kernel produced: a B-Rep source and a mesh."""
    out = tmp_path / "converted"
    result = import_cad(FIXTURES / "box.step", "step", out_dir=out)
    assert result.ok, result.error
    assert (out / "body_1.brep").stat().st_size > 0
    assert (out / "body_1.stl").stat().st_size > 0


def test_a_file_that_is_not_cad_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "not-really.step"
    fake.write_text("ISO-10303-21;\nHEADER;\nthis is not a real STEP file\n")
    result = import_cad(fake, "step")
    assert not result.ok
    assert result.error is not None
    assert result.error.code in ("cad_unreadable", "cad_empty")


def test_the_dispatcher_routes_cad_to_the_kernel() -> None:
    """An uploaded .step goes through the same public entry point as any other file."""
    result = importers.import_metadata(FIXTURES / "box.step", "step")
    assert result.ok, result.error
    assert result.metadata is not None
    assert result.metadata.parser.startswith("geometry-service/")
    assert "step" in importers.SUPPORTED and "iges" in importers.SUPPORTED
