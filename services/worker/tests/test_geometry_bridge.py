"""Geometry-service bridge. Skipped unless the OCCT binary is on PATH (the worker image has it)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import trimesh

from worker import geometry

pytestmark = pytest.mark.skipif(not geometry.available(), reason="geometry-service binary missing")


def box_plan(**overrides: object) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "goal": "box",
        "operations": [
            {
                "id": "b",
                "type": "create_box",
                "schema_version": 1,
                "width_mm": 200,
                "depth_mm": 100,
                "height_mm": 50,
                **overrides,
            }
        ],
    }


def test_execute_box_reports_and_writes_outputs(tmp_path: Path) -> None:
    result = geometry.execute_plan(box_plan(), tmp_path / "out")
    assert result.ok, result.error
    assert result.kernel.startswith("occt/") and result.units == "mm"
    (body,) = result.bodies
    assert body.name == "b" and body.valid and body.solids == 1
    assert body.bbox_mm.size == (200.0, 100.0, 50.0)
    assert body.volume_mm3 == pytest.approx(1_000_000)
    assert body.brep is not None and body.stl is not None
    assert (tmp_path / "out" / body.brep).exists() and (tmp_path / "out" / body.stl).exists()
    mesh = trimesh.load(tmp_path / "out" / body.stl, file_type="stl", force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight and mesh.volume == pytest.approx(1_000_000, rel=1e-6)
    assert len(body.brep_sha256) == 64 and len(body.stl_sha256) == 64


def test_same_plan_same_hashes(tmp_path: Path) -> None:
    a = geometry.execute_plan(box_plan(), tmp_path / "a")
    b = geometry.execute_plan(box_plan(), tmp_path / "b")
    assert a.ok and b.ok
    assert a.bodies[0].brep_sha256 == b.bodies[0].brep_sha256
    assert a.bodies[0].stl_sha256 == b.bodies[0].stl_sha256
    c = geometry.execute_plan(box_plan(height_mm=51), tmp_path / "c")
    assert c.ok and c.bodies[0].stl_sha256 != a.bodies[0].stl_sha256


def test_kernel_failure_is_structured(tmp_path: Path) -> None:
    plan = box_plan()
    plan["operations"].append(
        {
            "id": "f",
            "type": "fillet",
            "schema_version": 1,
            "target": "b",
            "edges": {"kind": "edges_parallel_to", "axis": "z"},
            "radius_mm": 80,
        }
    )
    result = geometry.execute_plan(plan, tmp_path / "out")
    assert not result.ok and result.error is not None
    assert result.error.code == "fillet_failed" and result.error.operation_id == "f"
    assert not list((tmp_path / "out").glob("*.stl"))  # nothing written on failure


def test_example_plans_execute(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "examples"
    if not examples.is_dir():
        pytest.skip("examples not available outside the monorepo")
    for path in sorted(examples.glob("*.plan.json")):
        result = geometry.execute_plan(json.loads(path.read_text("utf-8")), tmp_path / path.stem)
        assert result.ok, (path.name, result.error)
        assert len(result.bodies) == 1 and result.bodies[0].valid
