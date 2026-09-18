"""T-094: the printability score is a number a user acts on, so it is pinned.

Each fixture is a shape with an obvious verdict, and its expected score, subscores and
warning codes are recorded in a golden file. A change in the geometry heuristics shows up
here as an explicit diff to approve, not as a silently different number on someone's
screen. Regenerate with:

    uv run python tests/record_printcheck_golden.py
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import trimesh

from worker import printcheck as pc

GOLDEN = Path(__file__).with_name("printcheck_golden.json")
TOLERANCE = 0.51  # scores are reported to the user as whole numbers


def box(x: float, y: float, z: float) -> trimesh.Trimesh:
    mesh: trimesh.Trimesh = trimesh.creation.box(extents=(x, y, z))
    return mesh


def plate() -> trimesh.Trimesh:
    return box(80, 60, 3)


def tower() -> trimesh.Trimesh:
    """Tall and narrow: stable enough to print, but the footprint is the weak point."""
    return box(12, 12, 120)


def thin_wall() -> trimesh.Trimesh:
    return box(40, 0.3, 20)


def overhanging_t() -> trimesh.Trimesh:
    post = box(10, 10, 30)
    post.apply_translation((0, 0, 15))
    bar = box(50, 10, 5)
    bar.apply_translation((0, 0, 32.5))
    union: trimesh.Trimesh = trimesh.boolean.union([post, bar])
    return union


def too_big() -> trimesh.Trimesh:
    return box(400, 400, 400)


FIXTURES: dict[str, Callable[[], trimesh.Trimesh]] = {
    "clean_box": lambda: box(40, 20, 10),
    "flat_plate": plate,
    "tall_tower": tower,
    "thin_wall": thin_wall,
    "overhanging_t": overhanging_t,
    "larger_than_the_bed": too_big,
}


def snapshot(analysis: pc.PrintAnalysis) -> dict[str, Any]:
    return {
        "total": round(analysis.score.total, 2),
        "status": analysis.score.status,
        "subscores": {s.name: round(s.score, 2) for s in analysis.score.subscores},
        "warnings": sorted(w.code for w in analysis.warnings),
        "watertight": analysis.watertight,
        "fits_bed": analysis.fits_bed,
    }


def golden() -> dict[str, Any]:
    fixtures: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))["fixtures"]
    return fixtures


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_scores_match_the_golden_file(name: str) -> None:
    expected = golden()[name]
    observed = snapshot(pc.analyze(FIXTURES[name]()))

    assert observed["status"] == expected["status"], name
    assert observed["total"] == pytest.approx(expected["total"], abs=TOLERANCE), name
    assert observed["warnings"] == expected["warnings"], name
    assert observed["watertight"] == expected["watertight"], name
    assert observed["fits_bed"] == expected["fits_bed"], name
    for subscore, value in expected["subscores"].items():
        assert observed["subscores"][subscore] == pytest.approx(value, abs=TOLERANCE), (
            f"{name}.{subscore}"
        )


def test_every_fixture_is_recorded() -> None:
    assert set(FIXTURES) == set(golden()), "a fixture without a recorded score proves nothing"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_analysis_is_deterministic(name: str) -> None:
    mesh = FIXTURES[name]()
    assert snapshot(pc.analyze(mesh)) == snapshot(pc.analyze(mesh.copy()))


def test_the_golden_file_says_which_heuristics_produced_it() -> None:
    meta = json.loads(GOLDEN.read_text(encoding="utf-8"))
    analysis = pc.analyze(FIXTURES["clean_box"]())
    assert meta["_heuristics_version"] == analysis.heuristics_version, (
        "the heuristics changed: re-record the golden scores and say why in the commit"
    )
