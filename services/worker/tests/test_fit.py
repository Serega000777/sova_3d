"""T-129 (F-027): two parts, one verdict — and the numbers behind it."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import trimesh

from tests.fixtures import export_bytes
from worker.fit import FitRequest, Placement, check_fit, run_in_sandbox


def host_with_hole(diameter: float = 10.0) -> trimesh.Trimesh:
    block = trimesh.creation.box(extents=(30, 30, 10))
    block.apply_translation([15, 15, 5])
    hole = trimesh.creation.cylinder(radius=diameter / 2, height=12)
    hole.apply_translation([15, 15, 5])
    bored: trimesh.Trimesh = block.difference(hole)
    return bored


def peg(diameter: float) -> trimesh.Trimesh:
    cylinder: trimesh.Trimesh = trimesh.creation.cylinder(radius=diameter / 2, height=20)
    return cylinder


@pytest.mark.parametrize(
    ("diameter", "verdict"),
    [
        (10.4, "collides"),
        (10.0, "press"),
        (9.85, "transition"),
        (9.7, "sliding"),
        (9.0, "loose"),
    ],
)
def test_a_peg_in_a_10_mm_hole_gets_the_fit_it_deserves(diameter: float, verdict: str) -> None:
    result = check_fit(host_with_hole(), peg(diameter), FitRequest())
    assert result.ok and result.verdict == verdict, result


def test_a_collision_says_how_deep_and_where() -> None:
    result = check_fit(host_with_hole(), peg(10.4), FitRequest())
    assert result.verdict == "collides"
    assert result.max_penetration_mm == pytest.approx(0.2, abs=0.03)  # radial: (10.4 - 10) / 2
    assert result.min_clearance_mm is None
    assert result.interference_mm3 == pytest.approx(64.1, rel=0.05)  # π(5.2² − 5²) · 10
    assert result.contact is not None and result.contact.points > 0
    # the overlap is around the hole, inside the block's height
    assert result.contact.bbox_min_mm[2] >= -0.1 and result.contact.bbox_max_mm[2] <= 10.1
    assert 0.2 < result.b_inside_a_fraction < 0.7  # the part of the peg inside the block


def test_a_fit_reports_the_gap_per_side() -> None:
    result = check_fit(host_with_hole(), peg(9.7), FitRequest())
    assert result.min_clearance_mm == pytest.approx(0.15, abs=0.02)
    assert result.max_penetration_mm == 0.0


def test_placement_moves_part_b() -> None:
    far = Placement(offset_mm=(50, 0, 0))
    result = check_fit(host_with_hole(), peg(9.7), FitRequest(placement=far))
    assert result.verdict == "apart" and result.min_clearance_mm is not None
    assert result.min_clearance_mm > 20
    assert result.b_bbox_mm[0][0] > 40  # B's min x moved right


def test_the_same_pair_gets_the_same_answer() -> None:
    first = check_fit(host_with_hole(), peg(9.7), FitRequest())
    second = check_fit(host_with_hole(), peg(9.7), FitRequest())
    assert first == second


def test_fitting_runs_in_the_sandbox() -> None:
    tmp = Path(tempfile.mkdtemp())
    a = tmp / "host.stl"
    b = tmp / "peg.stl"
    a.write_bytes(export_bytes(host_with_hole(), "stl"))
    b.write_bytes(export_bytes(peg(10.4), "stl"))
    result = run_in_sandbox(a, "stl", b, "stl", FitRequest())
    assert result.ok, result.message
    assert result.verdict == "collides"
