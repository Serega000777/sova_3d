"""T-023 integrity report, T-024 STL export, T-025 GLB export, T-026 printable gate."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from tests import fixtures
from worker import exporters, sandbox
from worker.importers.child import parse
from worker.integrity import CheckStatus, IntegrityReport, build_report

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)


def contracts_dir() -> Path:
    """packages/contracts in the monorepo; absent inside the worker image."""
    root = Path(__file__).resolve()
    for parent in root.parents:
        candidate = parent / "packages" / "contracts"
        if candidate.is_dir():
            return candidate
    pytest.skip("packages/contracts not available (running outside the monorepo)")


def check(report: IntegrityReport, check_id: str) -> CheckStatus:
    return next(c.status for c in report.checks if c.id == check_id)


# --- T-023 -----------------------------------------------------------------------------------


def test_report_has_machine_checks_and_user_summary(tmp_path: Path) -> None:
    source = parse("stl", fixtures.write_stl_binary(tmp_path / "a.stl"))
    output = parse("stl", fixtures.write_stl_ascii(tmp_path / "b.stl"))
    report = build_report(source, output, printable_gate=False)
    assert report.schema_version == 1
    assert report.status is CheckStatus.warned  # STL cannot store units
    assert {c.id for c in report.checks} == {
        "coordinates_finite",
        "bbox_size",
        "surface_area",
        "volume",
        "watertight",
        "face_count",
        "units_explicit",
    }
    assert check(report, "bbox_size") is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.warned
    assert "STL → STL" in report.summary and "units" in report.summary
    assert report.source.volume_mm3 == pytest.approx(1000.0)


def test_report_fails_when_volume_or_watertightness_is_lost(tmp_path: Path) -> None:
    closed = parse("stl", fixtures.write_stl_binary(tmp_path / "closed.stl"))
    opened = parse("stl", fixtures.write_stl_open(tmp_path / "open.stl"))
    report = build_report(closed, opened, printable_gate=False)
    assert report.status is CheckStatus.failed
    assert check(report, "watertight") is CheckStatus.failed
    assert check(report, "volume") is CheckStatus.failed
    assert check(report, "face_count") is CheckStatus.warned
    assert "open edges" in report.summary


def test_report_schema_is_published_to_contracts() -> None:
    """packages/contracts/integrity-report.schema.json must match the pydantic model."""
    expected = IntegrityReport.model_json_schema()
    published = json.loads((contracts_dir() / "integrity-report.schema.json").read_text("utf-8"))
    assert published == expected, "run: uv run python -m worker.integrity --emit-schema"


# --- T-024 / T-025 ---------------------------------------------------------------------------


def test_export_stl_from_obj_is_validated(tmp_path: Path) -> None:
    source = fixtures.write_obj_with_materials(tmp_path / "box.obj")
    outcome = exporters.export_mesh(source, "obj", "stl", tmp_path / "box.stl", limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None and outcome.report.status is CheckStatus.warned
    assert check(outcome.report, "bbox_size") is CheckStatus.passed
    assert check(outcome.report, "volume") is CheckStatus.passed
    assert check(outcome.report, "face_count") is CheckStatus.passed
    assert Path(outcome.output_path or "").stat().st_size > 84


def test_export_glb_scales_mm_to_metres_and_back(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "glb", tmp_path / "box.glb", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert report.output.bbox_size_mm is not None
    assert tuple(round(s, 3) for s in report.output.bbox_size_mm) == fixtures.BOX_MM
    assert check(report, "units_explicit") is CheckStatus.passed
    assert (tmp_path / "box.glb").read_bytes()[:4] == b"glTF"
    # on disk it is what the spec says: metres, and the model's height along +Y
    raw = trimesh.load(tmp_path / "box.glb", force="mesh", process=False)
    width, depth, height = fixtures.BOX_MM
    np.testing.assert_allclose(raw.extents, (width / 1000, height / 1000, depth / 1000))


def test_export_glb_to_stl_roundtrip(tmp_path: Path) -> None:
    source = fixtures.write_glb(tmp_path / "box.glb")
    outcome = exporters.export_mesh(source, "glb", "stl", tmp_path / "box.stl", limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None
    assert outcome.report.source.bbox_size_mm is not None
    assert tuple(round(s, 3) for s in outcome.report.source.bbox_size_mm) == (
        20000.0,
        5000.0,  # glTF's Y is up: it becomes the platform's Z
        10000.0,
    )
    assert check(outcome.report, "bbox_size") is CheckStatus.passed


def test_export_rejects_unsupported_target_and_bad_source(tmp_path: Path) -> None:
    unsupported = exporters.export_mesh(
        tmp_path / "x.stl", "stl", "abc", tmp_path / "x.abc", limits=FAST
    )
    assert not unsupported.ok and unsupported.error is not None
    assert unsupported.error.code == "unsupported_target"

    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"garbage")
    outcome = exporters.export_mesh(bad, "glb", "stl", tmp_path / "out.stl", limits=FAST)
    assert not outcome.ok and outcome.error is not None
    assert outcome.error.code == "convert_failed"
    assert not (tmp_path / "out.stl").exists()


# --- T-026 -----------------------------------------------------------------------------------


def test_printable_gate_blocks_open_mesh(tmp_path: Path) -> None:
    source = fixtures.write_stl_open(tmp_path / "open.stl")
    outcome = exporters.export_mesh(
        source, "stl", "stl", tmp_path / "print.stl", printable_gate=True, limits=FAST
    )
    assert not outcome.ok and outcome.error is None
    report = outcome.report
    assert report is not None and report.status is CheckStatus.failed
    assert check(report, "printable_topology") is CheckStatus.failed
    assert "Not print-ready" in report.summary and "Repair" in report.summary
    assert not (tmp_path / "print.stl").exists()  # never hand out a red file


def test_printable_gate_passes_manifold_mesh(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(
        source, "stl", "stl", tmp_path / "print.stl", printable_gate=True, limits=FAST
    )
    assert outcome.ok and outcome.report is not None
    assert check(outcome.report, "printable_topology") is CheckStatus.passed
    assert outcome.report.printable_gate is True


def test_export_3mf_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(
        source, "stl", "3mf", tmp_path / "box.3mf", printable_gate=True, limits=FAST
    )
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # 3MF carries units
    assert check(report, "printable_topology") is CheckStatus.passed
    assert check(report, "volume") is CheckStatus.passed
    assert (tmp_path / "box.3mf").read_bytes()[:2] == b"PK"


def test_export_dae_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "dae", tmp_path / "box.dae", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # our own <unit> tag
    assert check(report, "volume") is CheckStatus.passed
    text = (tmp_path / "box.dae").read_text("utf-8")
    assert '<unit meter="0.001" name="millimeter"/>' in text
    assert "<up_axis>Z_UP</up_axis>" in text  # the data is Z-up; trimesh's own tag lies


def test_export_usdz_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "usdz", tmp_path / "box.usdz", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # our own stage sets it
    assert check(report, "volume") is CheckStatus.passed
    assert (tmp_path / "box.usdz").read_bytes()[:2] == b"PK"  # a ZIP container
