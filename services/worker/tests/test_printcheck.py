"""T-056..T-067: print analysis schema, checks, estimates, score, orientation optimization."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from worker import printcheck as pc

PLA = pc.MaterialProfile()  # 1.24 g/cm3, 25 USD/kg


def box(x: float, y: float, z: float) -> trimesh.Trimesh:
    mesh: trimesh.Trimesh = trimesh.creation.box(extents=(x, y, z))
    return mesh


def t_shape() -> trimesh.Trimesh:
    """10x10 post, 30 tall, with a 50x10x5 bar on top: overhangs on both sides."""
    post = box(10, 10, 30)
    post.apply_translation((0, 0, 15))
    bar = box(50, 10, 5)
    bar.apply_translation((0, 0, 32.5))
    union: trimesh.Trimesh = trimesh.boolean.union([post, bar])
    return union


def codes(analysis: pc.PrintAnalysis) -> set[str]:
    return {w.code for w in analysis.warnings}


# --- T-056 schema -----------------------------------------------------------------------------


def test_schema_has_typed_warnings_and_is_published() -> None:
    schema = pc.PrintAnalysis.model_json_schema()
    warning = schema["$defs"]["PrintWarning"]
    assert warning["properties"]["severity"]["enum"] == ["info", "warning", "error"]
    contracts = Path(__file__).resolve()
    for parent in contracts.parents:
        candidate = parent / "packages" / "contracts" / "print-analysis.schema.json"
        if candidate.exists():
            assert json.loads(candidate.read_text("utf-8")) == schema, (
                "run: uv run python -m worker.printcheck --emit-schema"
            )
            return
    pytest.skip("packages/contracts not available outside the monorepo")


# --- T-057 / T-058 -----------------------------------------------------------------------------


def test_clean_box_is_green_with_full_contact() -> None:
    analysis = pc.analyze(box(40, 20, 10))
    assert analysis.watertight and analysis.fits_bed
    assert analysis.score.status == "green" and analysis.score.total == 100
    assert analysis.metrics.contact_ratio == 1.0 and analysis.metrics.overhang_area_fraction == 0
    assert analysis.warnings == []
    assert analysis.metrics.bbox_mm == (40.0, 20.0, 10.0)


def test_open_mesh_fails_manifold_check() -> None:
    mesh = box(20, 20, 20)
    mesh.update_faces(np.asarray(mesh.face_normals)[:, 0] < 0.5)  # drop +X side
    analysis = pc.analyze(mesh)
    assert not analysis.watertight
    assert "not_manifold" in codes(analysis)
    assert analysis.score.status == "red" and analysis.score.total <= 49
    assert analysis.metrics.volume_mm3 is None and analysis.metrics.mass_g is None


def test_bed_fit_uses_printer_volume_and_allows_yaw() -> None:
    printer = pc.PrinterProfile(bed_x_mm=100, bed_y_mm=50, bed_z_mm=60)
    assert pc.analyze(box(40, 90, 10), printer=printer).fits_bed  # fits when rotated 90°
    too_tall = pc.analyze(box(10, 10, 70), printer=printer)
    assert not too_tall.fits_bed and "exceeds_bed" in codes(too_tall)
    assert too_tall.score.status == "red"
    assert too_tall.warnings[0].details["z_margin_mm"] == -10


# --- T-059 / T-060 -----------------------------------------------------------------------------


def test_thin_wall_fixture_is_detected() -> None:
    fin = box(20, 0.4, 10)
    fin.apply_translation((0, 0, 10))
    part = trimesh.boolean.union([box(20, 20, 10), fin])
    analysis = pc.analyze(part)  # 0.4 mm nozzle -> 0.8 mm minimum wall
    assert analysis.metrics.min_wall_mm == pytest.approx(0.4, abs=0.05)
    assert analysis.metrics.thin_area_fraction > 0.1
    assert "thin_walls" in codes(analysis)
    assert pc.analyze(box(20, 20, 10)).metrics.thin_area_fraction == 0


def test_overhang_heuristic_is_orientation_aware() -> None:
    upright = pc.analyze(t_shape())
    assert "overhangs" in codes(upright)
    assert upright.metrics.overhang_area_fraction == pytest.approx(0.1429, abs=0.01)
    assert upright.metrics.support_volume_mm3 == pytest.approx(12_000, rel=0.01)  # 2 x 20x10 x 30

    flipped = pc.analyze(t_shape(), orientation=pc.Orientation(rot_x_deg=180, label="upside down"))
    assert flipped.metrics.overhang_area_fraction == 0
    assert flipped.metrics.support_volume_mm3 == 0 and flipped.metrics.contact_ratio == 1.0


# --- T-061 / T-062 -----------------------------------------------------------------------------


def test_mass_and_cost_units() -> None:
    analysis = pc.analyze(box(100, 100, 100))  # 1 000 000 mm^3 = 1000 cm^3
    assert analysis.metrics.mass_g == pytest.approx(1240.0)
    assert analysis.metrics.material_cost == pytest.approx(31.0)  # 1.24 kg x 25 USD
    assert analysis.metrics.currency == "USD"
    petg = pc.MaterialProfile(name="PETG", density_g_cm3=1.27, price_per_kg=30, currency="EUR")
    eur = pc.analyze(box(100, 100, 100), material=petg)
    assert eur.metrics.mass_g == pytest.approx(1270.0) and eur.metrics.currency == "EUR"
    assert eur.metrics.total_cost == pytest.approx(38.1)


def test_support_material_is_costed_separately() -> None:
    analysis = pc.analyze(t_shape())
    assert analysis.metrics.support_mass_g == pytest.approx(12_000 / 1000 * 1.24, rel=0.01)
    assert analysis.metrics.total_cost == pytest.approx(
        (analysis.metrics.material_cost or 0) + (analysis.metrics.support_cost or 0)
    )
    assert analysis.metrics.print_time_min and analysis.metrics.layers == 175


# --- T-063 --------------------------------------------------------------------------------------


def test_score_is_weighted_and_explainable() -> None:
    analysis = pc.analyze(t_shape())
    weights = {s.name: s.weight for s in analysis.score.subscores}
    assert weights == {
        "geometry": 0.3,
        "walls": 0.2,
        "overhangs": 0.2,
        "bed_fit": 0.2,
        "stability": 0.1,
    }
    assert sum(weights.values()) == pytest.approx(1.0)
    total = sum(s.score * s.weight for s in analysis.score.subscores)
    assert analysis.score.total == pytest.approx(total, abs=0.1)
    assert all(s.reason for s in analysis.score.subscores)
    assert "Printability" in analysis.summary and "support" in analysis.summary.lower()


def test_score_is_deterministic() -> None:
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=15)
    a, b = pc.analyze(sphere), pc.analyze(sphere)
    assert a.model_dump() == b.model_dump()


# --- T-065 .. T-067 ----------------------------------------------------------------------------


def test_orientation_candidates_and_best_choice() -> None:
    cands = pc.candidates(t_shape())
    assert len(cands) == len(pc.CANDIDATE_ORIENTATIONS)
    labels = {c.orientation.label for c in cands}
    assert {"as modelled", "upside down", "front face down"} <= labels
    best = pc.best_candidate(cands)
    assert best.orientation.label == "upside down"
    assert best.support_volume_mm3 == 0 and best.score == 100


def test_optimize_is_non_destructive_and_reports_candidates() -> None:
    mesh = t_shape()
    before = np.asarray(mesh.vertices).copy()
    result = pc.optimize(mesh)
    assert np.array_equal(np.asarray(mesh.vertices), before)  # input untouched
    assert result.recommended is not None
    assert result.orientation == result.recommended.orientation
    assert result.score.total == result.recommended.score
    assert len(result.candidates) == len(pc.CANDIDATE_ORIENTATIONS)
    rotated = pc.apply_orientation(mesh, result.recommended.orientation)
    assert rotated.bounds[0].tolist() == pytest.approx([0, 0, 0])
    assert rotated.volume == pytest.approx(mesh.volume)


# --- sandboxed file entry ----------------------------------------------------------------------


def test_analyze_file_runs_in_sandbox(tmp_path: Path) -> None:
    from tests import fixtures
    from worker import sandbox

    stl = tmp_path / "t.stl"
    stl.write_bytes(fixtures.export_bytes(t_shape(), "stl"))
    fast = sandbox.SandboxLimits(wall_seconds=120, isolate_network=False)
    outcome = pc.analyze_file(stl, limits=fast)
    assert outcome.ok and outcome.analysis is not None
    assert "overhangs" in {w.code for w in outcome.analysis.warnings}

    rotated = tmp_path / "rotated.stl"
    optimized = pc.analyze_file(stl, optimize=True, apply_to=rotated, limits=fast)
    assert optimized.ok and optimized.analysis is not None
    assert optimized.analysis.recommended is not None
    assert optimized.analysis.recommended.orientation.label == "upside down"
    mesh = trimesh.load(rotated, file_type="stl", force="mesh")
    assert isinstance(mesh, trimesh.Trimesh) and mesh.bounds[0].tolist() == pytest.approx([0, 0, 0])

    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"solid nothing\nendsolid nothing\n")
    failed = pc.analyze_file(bad, limits=fast)
    assert not failed.ok and failed.error is not None and failed.error["code"] == "analysis_failed"
