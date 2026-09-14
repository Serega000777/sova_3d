"""T-027 diagnostics detect known defects; T-028..T-030 repairs fix golden fixtures."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from tests import fixtures
from worker import repair, sandbox
from worker.repair import diagnose, repair_mesh

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)


# --- golden defect fixtures -----------------------------------------------------------------


def flipped_box() -> trimesh.Trimesh:
    """Every face wound inward: consistent but inverted."""
    mesh = fixtures.box()
    mesh.invert()
    return mesh


def mixed_winding_box() -> trimesh.Trimesh:
    """Half the faces flipped: inconsistent winding."""
    mesh = fixtures.box()
    faces = np.asarray(mesh.faces).copy()
    faces[::2] = faces[::2, ::-1]
    mesh.faces = faces
    return mesh


def box_with_hole() -> trimesh.Trimesh:
    """Box missing its +X side (two coplanar triangles) => one planar 4-edge hole."""
    mesh = fixtures.box()
    mesh.update_faces(np.asarray(mesh.face_normals)[:, 0] < 0.5)
    return mesh


def box_with_degenerate_and_duplicate() -> trimesh.Trimesh:
    mesh = fixtures.box()
    faces = np.asarray(mesh.faces)
    zero_area = np.array([[0, 0, 1], [2, 2, 2]])  # collapsed triangles
    duplicate = faces[:1]
    mesh = trimesh.Trimesh(
        vertices=np.vstack([mesh.vertices, [[99.0, 99.0, 99.0]]]),  # unreferenced vertex
        faces=np.vstack([faces, zero_area, duplicate]),
        process=False,
    )
    return mesh


def non_manifold_fin() -> trimesh.Trimesh:
    """A box plus one extra triangle hanging off an existing edge: 3 faces share that edge."""
    mesh = fixtures.box()
    edge = np.asarray(mesh.faces)[0][:2]
    fin_vertex = len(mesh.vertices)
    return trimesh.Trimesh(
        vertices=np.vstack([mesh.vertices, [[30.0, 30.0, 30.0]]]),
        faces=np.vstack([mesh.faces, [[edge[0], edge[1], fin_vertex]]]),
        process=False,
    )


# --- T-027 -----------------------------------------------------------------------------------


def test_diagnose_clean_box() -> None:
    d = diagnose(fixtures.box())
    assert d.defects == []
    assert d.watertight and d.winding_consistent and not d.inverted
    assert d.holes == 0 and d.non_manifold_edges == 0 and d.boundary_edges == 0
    assert d.volume_mm3 == pytest.approx(1000.0) and d.euler_number == 2


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (flipped_box, {"inverted_normals"}),
        (mixed_winding_box, {"inconsistent_winding"}),
        (box_with_hole, {"holes"}),
        (
            box_with_degenerate_and_duplicate,
            {"degenerate_faces", "duplicate_faces", "unreferenced_vertices"},
        ),
        (non_manifold_fin, {"non_manifold_edges"}),
    ],
)
def test_diagnose_detects_known_defects(factory, expected: set[str]) -> None:  # type: ignore[no-untyped-def]
    d = diagnose(factory())
    assert expected <= set(d.defects), d


def test_diagnose_counts_are_exact() -> None:
    d = diagnose(box_with_hole())
    assert d.holes == 1 and d.boundary_edges == 4 and d.faces == 10
    d = diagnose(box_with_degenerate_and_duplicate())
    assert d.degenerate_faces == 2 and d.duplicate_faces == 1 and d.unreferenced_vertices == 1
    d = diagnose(non_manifold_fin())
    assert d.non_manifold_edges == 1


# --- T-028 -----------------------------------------------------------------------------------


def test_normal_repair_orients_outward() -> None:
    mesh = flipped_box()
    report = repair_mesh(mesh, steps=("normals",))
    assert report.before.inverted and not report.after.inverted
    assert report.delta.faces_flipped == 12
    assert report.after.volume_mm3 == pytest.approx(1000.0)
    assert mesh.volume > 0


def test_normal_repair_makes_winding_consistent() -> None:
    mesh = mixed_winding_box()
    report = repair_mesh(mesh, steps=("normals",))
    assert not report.before.winding_consistent and report.after.winding_consistent
    assert report.delta.faces_flipped == 6
    assert report.changed and report.printable_after


# --- T-029 -----------------------------------------------------------------------------------


def test_hole_closing_reports_changed_topology() -> None:
    mesh = box_with_hole()
    report = repair_mesh(mesh, steps=("holes",))
    assert report.before.holes == 1 and report.after.holes == 0
    assert report.delta.holes_closed == 1 and report.delta.holes_remaining == 0
    assert report.delta.faces_added >= 2
    assert report.after.watertight and report.printable_after
    assert report.after.volume_mm3 == pytest.approx(1000.0)


def test_large_hole_uses_fan_fill() -> None:
    """Remove a whole side of a subdivided box: a 16-edge loop trimesh's fill_holes skips."""
    mesh = fixtures.box().subdivide().subdivide()
    normals = np.asarray(mesh.face_normals)
    mesh.update_faces(normals[:, 2] < 0.5)  # drop the +Z cap
    before = diagnose(mesh)
    assert before.holes == 1 and before.boundary_edges > 4
    report = repair_mesh(mesh, steps=("holes",))
    assert report.after.watertight, report
    assert report.delta.vertices_added == 1  # the fan centroid
    assert report.after.volume_mm3 == pytest.approx(1000.0, rel=1e-6)


# --- T-030 -----------------------------------------------------------------------------------


def test_degenerate_cleanup_leaves_no_zero_area_faces() -> None:
    mesh = box_with_degenerate_and_duplicate()
    report = repair_mesh(mesh, steps=("degenerate",))
    assert report.before.degenerate_faces == 2 and report.before.duplicate_faces == 1
    assert report.after.degenerate_faces == 0 and report.after.duplicate_faces == 0
    assert report.after.unreferenced_vertices == 0
    assert report.delta.faces_removed == 3 and report.delta.vertices_removed == 1
    assert np.all(mesh.area_faces > 0)


# --- full pipeline -----------------------------------------------------------------------------


def test_full_repair_on_multiply_broken_mesh() -> None:
    mesh = box_with_hole()
    faces = np.asarray(mesh.faces).copy()
    faces[::3] = faces[::3, ::-1]  # also scramble winding
    mesh.faces = np.vstack([faces, [[0, 0, 1]]])  # and add a degenerate face
    report = repair_mesh(mesh)
    assert report.steps == ["degenerate", "normals", "holes"]
    assert report.after.defects == []
    assert report.printable_after and report.changed
    assert report.after.volume_mm3 == pytest.approx(1000.0)


def test_repair_file_roundtrip_through_sandbox(tmp_path: Path) -> None:
    source = tmp_path / "open.stl"
    source.write_bytes(fixtures.export_bytes(box_with_hole(), "stl"))
    outcome = repair.repair_in_sandbox(source, "stl", tmp_path / "repaired.stl", limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None and outcome.report.printable_after
    repaired = trimesh.load(tmp_path / "repaired.stl", file_type="stl", force="mesh")
    assert isinstance(repaired, trimesh.Trimesh)
    assert repaired.is_watertight and repaired.volume == pytest.approx(1000.0)
    assert source.read_bytes() == fixtures.export_bytes(box_with_hole(), "stl")  # untouched


def test_repair_in_sandbox_surfaces_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"solid nothing\nendsolid nothing\n")
    outcome = repair.repair_in_sandbox(bad, "stl", tmp_path / "out.stl", limits=FAST)
    assert not outcome.ok and outcome.error is not None
    assert outcome.error.code == "repair_failed"
    assert not (tmp_path / "out.stl").exists()
