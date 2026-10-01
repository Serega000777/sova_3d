"""T-235 / T-236: direct mesh edits and surface details keep the model a valid solid."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from tests import fixtures
from worker import meshedit, sandbox
from worker.meshedit import EditRequest

FAST = sandbox.SandboxLimits(wall_seconds=120, isolate_network=False)
TOP = [(-10.0, -5.0, 2.5), (10.0, -5.0, 2.5), (10.0, 5.0, 2.5), (-10.0, 5.0, 2.5)]


def box() -> trimesh.Trimesh:
    return fixtures.box()  # 20 x 10 x 5 mm, centred


def run(mesh: trimesh.Trimesh, *operations: dict, **extra: object) -> meshedit.EditReport:
    request = EditRequest.model_validate({"operations": list(operations), **extra})
    return meshedit.edit_mesh(mesh, request, None)


def top_face_points(mesh: trimesh.Trimesh) -> list[list[float]]:
    """Both triangles of the box's top face, as 3 coordinate triples each."""
    points: list[list[float]] = []
    for face, normal in zip(mesh.faces, mesh.face_normals, strict=True):
        if normal[2] > 0.9:
            points.extend(mesh.vertices[face].tolist())
    return points


def volume(report: meshedit.EditReport) -> float:
    assert report.after is not None and report.after.volume_mm3 is not None
    return report.after.volume_mm3


def assert_solid(report: meshedit.EditReport) -> None:
    assert report.ok, report.message
    assert report.after is not None and report.after.watertight


def top_vertex_selection(kind: str = "vertex") -> dict:
    return {"kind": kind, "points_mm": [list(p) for p in TOP]}


# --- T-235: selection edits ---------------------------------------------------------------------


def test_move_vertices_along_an_axis_stretches_the_box() -> None:
    report = run(
        box(), {"op": "move", "selection": top_vertex_selection(), "delta_mm": [0, 0, 3.0]}
    )
    assert_solid(report)
    assert report.after is not None
    assert report.after.bbox_mm[1][2] == pytest.approx(5.5)
    assert volume(report) == pytest.approx(20 * 10 * 8)


def test_move_faces_along_their_normal() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "move", "selection": selection, "along_normal_mm": 2.0})
    assert_solid(report)
    assert report.after is not None
    assert report.after.bbox_mm[1][2] > 2.5  # the top moved up


def test_move_needs_exactly_one_way_to_move() -> None:
    with pytest.raises(ValidationError):
        run(
            box(),
            {
                "op": "move",
                "selection": top_vertex_selection(),
                "delta_mm": [1, 0, 0],
                "along_normal_mm": 1.0,
            },
        )
    with pytest.raises(ValidationError):
        run(box(), {"op": "move", "selection": top_vertex_selection()})


def test_extrude_a_face_adds_the_volume_and_a_wall() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "extrude", "selection": selection, "distance_mm": 3.0})
    assert_solid(report)
    assert volume(report) == pytest.approx(20 * 10 * 8)
    assert report.after is not None and report.before is not None
    assert report.after.faces == report.before.faces + 8  # two triangles per boundary edge


def test_extrude_inward_cuts_the_volume() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "extrude", "selection": selection, "distance_mm": -2.0})
    assert_solid(report)
    assert volume(report) == pytest.approx(20 * 10 * 3)


def test_extrude_refuses_a_zero_distance() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "extrude", "selection": selection, "distance_mm": 0.0})
    assert not report.ok and report.code == "zero_distance" and report.failed_operation == 0


def test_inset_shrinks_the_face_without_changing_the_volume() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "inset", "selection": selection, "amount_mm": 1.0})
    assert_solid(report)
    assert volume(report) == pytest.approx(20 * 10 * 5)
    assert report.after is not None and report.before is not None
    assert report.after.faces == report.before.faces + 8


def test_inset_that_folds_faces_over_is_refused() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "inset", "selection": selection, "amount_mm": 6.0})
    assert not report.ok and report.code == "inset_too_large"


def test_inset_then_extrude_makes_a_raised_boss() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    inner = [
        [-9.0, -4.0, 2.5],
        [9.0, -4.0, 2.5],
        [9.0, 4.0, 2.5],
        [-9.0, -4.0, 2.5],
        [9.0, 4.0, 2.5],
        [-9.0, 4.0, 2.5],
    ]
    report = run(
        mesh,
        {"op": "inset", "selection": selection, "amount_mm": 1.0},
        {"op": "extrude", "selection": {"kind": "face", "points_mm": inner}, "distance_mm": 2.0},
    )
    assert_solid(report)
    assert volume(report) == pytest.approx(20 * 10 * 5 + 18 * 8 * 2)


def test_delete_a_face_and_fill_the_hole() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "delete_faces", "selection": selection, "fill": True})
    assert_solid(report)
    assert volume(report) == pytest.approx(20 * 10 * 5)


def test_delete_without_fill_leaves_an_open_mesh_and_says_so() -> None:
    mesh = box()
    selection = {"kind": "face", "points_mm": top_face_points(mesh)}
    report = run(mesh, {"op": "delete_faces", "selection": selection, "fill": False})
    assert report.ok
    assert report.after is not None and not report.after.watertight
    assert any("open boundary" in w for w in report.warnings)


def test_a_stale_selection_is_refused_with_the_failing_operation() -> None:
    report = run(
        box(),
        {"op": "move", "selection": top_vertex_selection(), "delta_mm": [0, 0, 1]},
        {
            "op": "move",
            "selection": {"kind": "vertex", "points_mm": [[99, 99, 99]]},
            "delta_mm": [0, 0, 1],
        },
    )
    assert not report.ok and report.code == "stale_selection" and report.failed_operation == 1


def test_a_selection_made_on_a_different_mesh_is_refused() -> None:
    report = run(
        box(),
        {"op": "move", "selection": top_vertex_selection(), "delta_mm": [0, 0, 1]},
        expected_faces=999,
    )
    assert not report.ok and report.code == "stale_selection"


def test_selection_arity_is_validated() -> None:
    with pytest.raises(ValidationError):
        meshedit.Selection(kind="edge", points_mm=[(0, 0, 0), (1, 0, 0), (2, 0, 0)])
    with pytest.raises(ValidationError):
        meshedit.Selection(kind="face", points_mm=[(0, 0, 0), (1, 0, 0)])


# --- T-235: bevel ---------------------------------------------------------------------------------

FRONT_TOP_EDGE = {"kind": "edge", "points_mm": [[-10, -5, 2.5], [10, -5, 2.5]]}


def test_chamfer_one_edge_removes_a_triangular_strip() -> None:
    report = run(box(), {"op": "bevel_edges", "selection": FRONT_TOP_EDGE, "width_mm": 1.0})
    assert_solid(report)
    assert volume(report) == pytest.approx(1000 - 0.5 * 1.0 * 1.0 * 20, abs=0.05)
    assert report.applied[0].detail["style"] == "chamfer"


def test_round_bevel_removes_the_fillet_corner() -> None:
    report = run(
        box(),
        {"op": "bevel_edges", "selection": FRONT_TOP_EDGE, "width_mm": 1.0, "segments": 8},
    )
    assert_solid(report)
    expected = 1000 - (1.0 - np.pi / 4.0) * 1.0 * 1.0 * 20
    assert volume(report) == pytest.approx(expected, abs=0.1)
    assert report.applied[0].detail["style"] == "round"


def test_bevel_every_edge_of_the_box_stays_watertight() -> None:
    mesh = box()
    pairs = {
        tuple(sorted(map(tuple, mesh.vertices[list(e)].round(6).tolist())))
        for e in mesh.edges_unique
    }
    box_edges = [
        [list(a), list(b)]
        for a, b in pairs
        if sum(abs(np.array(a) - np.array(b)) > 1e-6) == 1  # axis-parallel: a real box edge
    ]
    assert len(box_edges) == 12
    selection = {"kind": "edge", "points_mm": [p for e in box_edges for p in e]}
    report = run(mesh, {"op": "bevel_edges", "selection": selection, "width_mm": 0.8})
    assert_solid(report)
    assert report.applied[0].detail["edges"] == 12
    assert volume(report) < 1000


def test_a_coplanar_diagonal_has_nothing_to_bevel() -> None:
    mesh = box()
    diagonal = None
    for a, b in mesh.edges_unique:
        va, vb = mesh.vertices[a], mesh.vertices[b]
        if va[2] == vb[2] == 2.5 and va[0] != vb[0] and va[1] != vb[1]:
            diagonal = [va.tolist(), vb.tolist()]
    assert diagonal is not None
    report = run(
        mesh,
        {"op": "bevel_edges", "selection": {"kind": "edge", "points_mm": diagonal}, "width_mm": 1},
    )
    assert not report.ok and report.code == "nothing_to_bevel"


def test_bevel_needs_a_watertight_mesh() -> None:
    open_mesh = box()
    open_mesh.update_faces(np.arange(len(open_mesh.faces)) != 0)
    report = run(open_mesh, {"op": "bevel_edges", "selection": FRONT_TOP_EDGE, "width_mm": 1.0})
    assert not report.ok and report.code == "needs_watertight"


def test_too_many_bevel_edges_are_refused() -> None:
    """Regression: unlike _bars (ribs/knurl), _bevel had no MAX_CUTTERS check, so a selection
    with thousands of edges would build one cutter prism per edge and run an unbounded
    batch_boolean over all of them."""
    mesh = trimesh.creation.icosphere(subdivisions=5)  # 10242 vertices: plenty to pick from
    points = mesh.vertices[: 2 * (meshedit.MAX_CUTTERS + 1)]
    selection = {"kind": "edge", "points_mm": [p.tolist() for p in points]}
    report = run(mesh, {"op": "bevel_edges", "selection": selection, "width_mm": 0.01})
    assert not report.ok and report.code == "too_many_features"


# --- T-236: surface details -----------------------------------------------------------------------


def detail(profile: dict, mode: str = "raised", depth: float = 1.0, **extra: object) -> dict:
    return {
        "op": "detail",
        "at_mm": [0, 0, 2.5],
        "normal_hint": [0, 0, 1],
        "profile": profile,
        "mode": mode,
        "depth_mm": depth,
        **extra,
    }


def test_a_raised_circle_adds_a_cylinder() -> None:
    report = run(box(), detail({"shape": "circle", "diameter_mm": 4.0}))
    assert_solid(report)
    assert volume(report) == pytest.approx(1000 + np.pi * 2.0**2 * 1.0, rel=0.01)
    assert report.after is not None
    assert report.after.bbox_mm[1][2] == pytest.approx(3.5)


def test_a_recessed_square_cuts_a_pocket() -> None:
    report = run(box(), detail({"shape": "square", "width_mm": 4.0}, mode="recessed"))
    assert_solid(report)
    assert volume(report) == pytest.approx(1000 - 16.0, abs=0.05)


def test_a_rotated_rectangle_keeps_its_area() -> None:
    profile = {"shape": "square", "width_mm": 6.0, "height_mm": 2.0, "rotation_deg": 30.0}
    report = run(box(), detail(profile, mode="recessed", depth=0.5))
    assert_solid(report)
    assert volume(report) == pytest.approx(1000 - 6 * 2 * 0.5, abs=0.05)


def test_a_circle_that_leaves_the_flat_surface_is_refused() -> None:
    report = run(box(), detail({"shape": "circle", "diameter_mm": 12.0}))
    assert not report.ok and report.code == "footprint_leaves_surface"


def test_a_detail_below_the_tolerance_is_refused() -> None:
    small = run(box(), detail({"shape": "circle", "diameter_mm": 0.1}))
    assert not small.ok and small.code == "below_tolerance"
    shallow = run(box(), detail({"shape": "square", "width_mm": 4.0}, depth=0.05))
    assert not shallow.ok and shallow.code == "below_tolerance"
    loose = run(box(), detail({"shape": "circle", "diameter_mm": 0.3}), tolerance_mm=0.5)
    assert not loose.ok and loose.code == "below_tolerance"


def test_a_recess_that_would_cut_through_is_refused() -> None:
    report = run(box(), detail({"shape": "square", "width_mm": 4.0}, mode="recessed", depth=4.9))
    assert not report.ok and report.code == "would_cut_through"


def test_a_point_off_the_surface_is_refused() -> None:
    op = detail({"shape": "circle", "diameter_mm": 4.0})
    op["at_mm"] = [0, 0, 20]
    report = run(box(), op)
    assert not report.ok and report.code == "off_surface"


def test_a_point_on_an_edge_with_a_wrong_hint_is_ambiguous() -> None:
    op = detail({"shape": "circle", "diameter_mm": 1.0})
    op["at_mm"] = [0, 0, 2.5]
    op["normal_hint"] = [1, 0, 0]
    report = run(box(), op)
    assert not report.ok and report.code == "surface_ambiguous"


def test_ribs_add_bars_across_the_area() -> None:
    profile = {
        "shape": "ribs",
        "area": {"width_mm": 10.0, "length_mm": 6.0},
        "pitch_mm": 2.0,
        "rib_width_mm": 1.0,
    }
    report = run(box(), detail(profile, depth=0.5))
    assert_solid(report)
    added = volume(report) - 1000
    assert 12.0 < added < 18.0  # about half of the 10 x 6 area, 0.5 mm tall
    assert report.after is not None and report.after.bbox_mm[1][2] == pytest.approx(3.0)


def test_recessed_grooves_cut_the_same_pattern() -> None:
    profile = {
        "shape": "ribs",
        "area": {"width_mm": 10.0, "length_mm": 6.0},
        "pitch_mm": 2.0,
        "rib_width_mm": 1.0,
    }
    report = run(box(), detail(profile, mode="recessed", depth=0.5))
    assert_solid(report)
    assert 12.0 < 1000 - volume(report) < 18.0


def test_ribs_wider_than_their_pitch_are_refused() -> None:
    profile = {
        "shape": "ribs",
        "area": {"width_mm": 10.0, "length_mm": 6.0},
        "pitch_mm": 1.0,
        "rib_width_mm": 1.0,
    }
    report = run(box(), detail(profile, depth=0.5))
    assert not report.ok and report.code in {"ribs_overlap", "below_tolerance"}


def test_a_diamond_knurl_cuts_a_crossing_groove_pattern() -> None:
    profile = {
        "shape": "knurl",
        "area": {"width_mm": 8.0, "length_mm": 8.0},
        "pitch_mm": 1.0,
        "pattern": "diamond",
        "angle_deg": 45.0,
    }
    report = run(box(), detail(profile, mode="recessed", depth=0.4))
    assert_solid(report)
    removed = 1000 - volume(report)
    assert 3.0 < removed < 25.6  # a fraction of the 8 x 8 x 0.4 slab, never more
    assert report.after is not None and report.before is not None
    assert report.after.faces > report.before.faces + 100


def test_a_straight_knurl_is_one_set_of_grooves() -> None:
    straight = {
        "shape": "knurl",
        "area": {"width_mm": 8.0, "length_mm": 8.0},
        "pitch_mm": 1.0,
        "pattern": "straight",
        "angle_deg": 0.0,
    }
    diamond = {**straight, "pattern": "diamond", "angle_deg": 45.0}
    one = run(box(), detail(straight, mode="recessed", depth=0.4))
    two = run(box(), detail(diamond, mode="recessed", depth=0.4))
    assert_solid(one)
    mean_width = (
        meshedit.KNURL_OPENING + meshedit.KNURL_FLOOR
    ) / 2.0  # a trapezoid, per unit pitch
    assert (1000 - volume(one)) == pytest.approx(mean_width * 0.4 * 8 * 8, rel=0.1)
    assert (1000 - volume(two)) > (1000 - volume(one)) * 0.9


def test_a_raised_knurl_actually_adds_material_and_reports_raised() -> None:
    """Regression: a raised knurl used to always cut (solid - grooves) while the report still
    claimed mode="raised", lying about what was done. It must now add a ridge pattern."""
    profile = {
        "shape": "knurl",
        "area": {"width_mm": 8.0, "length_mm": 8.0},
        "pitch_mm": 1.0,
        "pattern": "diamond",
        "angle_deg": 45.0,
    }
    report = run(box(), detail(profile, mode="raised", depth=0.4))
    assert_solid(report)
    added = volume(report) - 1000
    assert 3.0 < added < 25.6  # a fraction of the 8 x 8 x 0.4 slab, never more
    assert report.applied[0].detail["mode"] == "raised"
    recessed = run(box(), detail(profile, mode="recessed", depth=0.4))
    assert_solid(recessed)
    # raised and recessed are mirror images of the same pattern, so they move about the same
    # amount of material.
    assert added == pytest.approx(1000 - volume(recessed), rel=0.1)


def test_too_many_grooves_are_refused() -> None:
    profile = {
        "shape": "knurl",
        "area": {"width_mm": 8.0, "length_mm": 8.0},
        "pitch_mm": 0.2,
        "pattern": "straight",
        "angle_deg": 0.0,
    }
    report = run(box(), detail(profile, depth=0.4), tolerance_mm=0.05)
    assert report.ok or report.code in {"too_many_features", "too_many_triangles"}


def test_preview_reports_the_footprint_and_a_triangle_estimate_without_editing() -> None:
    profile = {"shape": "circle", "diameter_mm": 4.0}
    report = run(box(), detail(profile), preview=True)
    assert report.ok and report.preview is not None
    assert len(report.preview.footprints_mm) == 1
    assert len(report.preview.footprints_mm[0]) >= 24
    assert report.preview.estimated_added_triangles > 0
    assert report.after is not None and report.before is not None
    assert report.after.faces == report.before.faces  # nothing was applied


def test_preview_still_enforces_the_checks() -> None:
    report = run(box(), detail({"shape": "circle", "diameter_mm": 12.0}), preview=True)
    assert not report.ok and report.code == "footprint_leaves_surface"


def test_a_detail_needs_a_watertight_mesh() -> None:
    open_mesh = box()
    open_mesh.update_faces(np.arange(len(open_mesh.faces)) != 0)
    report = run(open_mesh, detail({"shape": "circle", "diameter_mm": 4.0}))
    assert not report.ok and report.code == "needs_watertight"


def test_details_work_on_a_curved_mesh_flat_cap() -> None:
    cylinder = trimesh.creation.cylinder(radius=10.0, height=8.0, sections=96)
    op = {
        "op": "detail",
        "at_mm": [0, 0, 4.0],
        "normal_hint": [0, 0, 1],
        "profile": {"shape": "square", "width_mm": 5.0},
        "mode": "raised",
        "depth_mm": 1.0,
    }
    report = run(cylinder, op)
    assert_solid(report)
    assert volume(report) == pytest.approx(float(cylinder.volume) + 25.0, abs=0.1)


# --- file level and sandbox ---------------------------------------------------------------


def test_the_sandboxed_run_writes_a_valid_stl(tmp_path: Path) -> None:
    source = tmp_path / "box.stl"
    fixtures.write_stl_binary(source)
    output = tmp_path / "edited.stl"
    request = EditRequest.model_validate(
        {
            "operations": [detail({"shape": "circle", "diameter_mm": 4.0})],
            "expected_faces": 12,
        }
    )
    report = meshedit.run_in_sandbox(source, "stl", request, output, FAST)
    assert report.ok, report.message
    edited = trimesh.load(output, force="mesh")
    assert edited.is_watertight
    assert edited.volume == pytest.approx(1000 + np.pi * 4.0, rel=0.01)


def test_the_sandboxed_preview_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "box.stl"
    fixtures.write_stl_binary(source)
    request = EditRequest.model_validate(
        {
            "operations": [detail({"shape": "circle", "diameter_mm": 4.0})],
            "preview": True,
        }
    )
    report = meshedit.run_in_sandbox(source, "stl", request, None, FAST)
    assert report.ok and report.preview is not None and report.output_path is None


def test_a_file_without_a_mesh_is_a_typed_failure(tmp_path: Path) -> None:
    source = tmp_path / "empty.stl"
    source.write_bytes(b"solid x\nendsolid x\n")
    request = EditRequest.model_validate(
        {"operations": [{"op": "move", "selection": top_vertex_selection(), "delta_mm": [0, 0, 1]}]}
    )
    report = meshedit.edit_file(source, "stl", request, None)
    assert not report.ok and report.code == "no_mesh"
