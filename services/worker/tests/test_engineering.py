"""T-117 (F-005): the facts an engineer measures before answering."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import trimesh

from tests.fixtures import export_bytes
from worker.engineering import FactsRequest, measure, measure_file, run_in_sandbox
from worker.paint import BoxRegion, LassoRegion


def open_box(wall: float = 1.2, floor: float = 2.0) -> trimesh.Trimesh:
    """A 60 × 40 × 30 tray with thin walls and a thicker floor, at the origin corner."""
    outer = trimesh.creation.box(extents=(60, 40, 30))
    outer.apply_translation([30, 20, 15])
    inner = trimesh.creation.box(extents=(60 - 2 * wall, 40 - 2 * wall, 30 - floor + 1))
    inner.apply_translation([30, 20, floor + (30 - floor + 1) / 2])
    tray: trimesh.Trimesh = outer.difference(inner)
    return tray


def test_walls_are_measured_where_they_are_thin() -> None:
    facts = measure(open_box(), FactsRequest(limit_mm=1.6))
    assert facts.ok and facts.walls is not None
    assert facts.walls.min_mm == pytest.approx(1.2, abs=0.05)
    assert facts.walls.median_mm == pytest.approx(1.2, abs=0.05)
    assert facts.walls.thin_fraction > 0.4  # most of the tray is its thin side walls
    assert facts.slenderness == pytest.approx(60 / 1.2, rel=0.1)


def test_the_region_the_user_drew_gets_its_own_measurement() -> None:
    # the floor, seen from below: a box region under the tray
    floor = BoxRegion(min_mm=[5, 5, -1], max_mm=[55, 35, 0.5])
    facts = measure(open_box(), FactsRequest(limit_mm=1.6, region=floor))
    assert facts.region_faces > 0 and facts.region_walls is not None
    assert facts.region_walls.median_mm == pytest.approx(2.0, abs=0.05)
    assert facts.region_walls.thin_fraction == 0.0

    # a side wall, outlined on its outside
    outline = [[10, 5], [30, 5], [30, 25], [10, 25]]
    side = LassoRegion(axis="x", offset_mm=0, depth_mm=3, points_mm=outline)
    facts = measure(open_box(), FactsRequest(limit_mm=1.6, region=side))
    assert facts.region_walls is not None
    assert facts.region_walls.median_mm == pytest.approx(1.2, abs=0.05)
    assert facts.region_walls.thin_fraction == 1.0


def test_mass_comes_from_the_volume_and_the_density() -> None:
    facts = measure(open_box(), FactsRequest(densities_g_cm3={"pla": 1.24, "petg": 1.27}))
    assert facts.watertight and facts.volume_mm3 is not None
    assert facts.mass_g["pla"] == pytest.approx(facts.volume_mm3 / 1000 * 1.24, rel=0.01)
    assert facts.mass_g["petg"] > facts.mass_g["pla"]


def test_the_same_part_measures_the_same_twice() -> None:
    first = measure(open_box(), FactsRequest())
    second = measure(open_box(), FactsRequest())
    assert first == second


def test_an_stl_file_is_stitched_before_it_is_measured() -> None:
    tmp = Path(tempfile.mkdtemp())
    source = tmp / "tray.stl"
    source.write_bytes(export_bytes(open_box(), "stl"))
    facts = measure_file(source, "stl", FactsRequest(densities_g_cm3={"pla": 1.24}))
    assert facts.watertight and facts.mass_g["pla"] > 0


def test_measuring_runs_in_the_sandbox() -> None:
    tmp = Path(tempfile.mkdtemp())
    source = tmp / "tray.stl"
    source.write_bytes(export_bytes(open_box(), "stl"))
    facts = run_in_sandbox(source, "stl", FactsRequest(limit_mm=1.6))
    assert facts.ok, facts.message
    assert facts.walls is not None and facts.walls.min_mm == pytest.approx(1.2, abs=0.05)
