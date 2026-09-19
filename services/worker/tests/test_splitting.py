"""T-141 (F-081): cut a model into printable parts — watertight, dowelled, laid out."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from worker.splitting import (
    Bed,
    Connectors,
    CutPlane,
    SplitRequest,
    cap_faces,
    dowel_spots,
    resolve_planes,
    run_in_sandbox,
    split_file,
    split_mesh,
)

pytest.importorskip("manifold3d")


def statuette() -> trimesh.Trimesh:
    """A body with a head: 40 mm wide, 153 mm tall — too tall for a small bed."""
    body = trimesh.creation.cylinder(radius=20, height=120, sections=64)
    body.apply_translation((0, 0, 60))
    head = trimesh.creation.icosphere(subdivisions=3, radius=18)
    head.apply_translation((0, 0, 135))
    merged = trimesh.boolean.union([body, head], engine="manifold")
    assert isinstance(merged, trimesh.Trimesh)
    return merged


def load(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, file_type="stl", force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    return mesh


def test_three_equal_parts_are_watertight_and_add_up(tmp_path: Path) -> None:
    statue = statuette()
    report = split_mesh(statue, SplitRequest(parts=3), tmp_path)
    assert report.ok, report.message
    assert [p.name for p in report.parts] == ["part_01", "part_02", "part_03"]
    assert [plane.source for plane in report.planes] == ["equal_parts"] * 2
    assert all(plane.axis == "z" for plane in report.planes)  # the longest extent
    # every part prints: closed, cut face down at the origin, no taller than a third
    for part in report.parts:
        mesh = load(tmp_path / part.file)
        assert mesh.is_watertight and mesh.is_volume
        assert np.allclose(mesh.bounds[0], 0, atol=1e-6)
        assert part.extents_mm[2] == pytest.approx(51.0)
        assert part.dowel_holes == 2
    # material is conserved: the parts plus what the dowel holes removed
    holes = sum(p.dowel_holes for p in report.parts) / 2
    hole_volume = holes * math.pi * (2.5 + 0.25) ** 2 * (12 + 0.5)
    assert sum(p.volume_mm3 for p in report.parts) + hole_volume == pytest.approx(
        statue.volume, rel=0.01
    )
    assert report.warnings == []
    # the dowels come along as parts of their own, standing on the plate
    assert len(report.dowels) == 4
    dowel = load(tmp_path / report.dowels[0].file)
    assert dowel.extents[2] == pytest.approx(12) and dowel.extents[0] == pytest.approx(5, abs=0.1)
    plate = load(tmp_path / "layout.stl")
    assert plate.extents[0] == pytest.approx(report.layout_extents_mm[0])
    assert len(plate.split(only_watertight=False)) == 7  # three parts and four dowels apart


def test_a_dowel_hole_sits_on_both_sides_of_the_cut(tmp_path: Path) -> None:
    plate = trimesh.creation.box(extents=(60, 30, 40))
    report = split_mesh(plate, SplitRequest(parts=2, axis="x"), tmp_path)
    assert report.ok
    lower, upper = (load(tmp_path / p.file) for p in report.parts)
    # the cut face (30 x 40) beats the part's own underside (30 x 30), so it becomes the
    # base: the 30 mm half of the x span is the height now
    for part in (lower, upper):
        assert part.extents[2] == pytest.approx(30)
        base = cap_faces(part, np.zeros(3), np.array([0.0, 0.0, -1.0]))
        assert len(base) > 0
    # the holes: rays up through the base find two round pockets 6.25 mm deep
    for part in (lower, upper):
        xs = np.arange(0.5, part.extents[0], 1.0)
        ys = np.arange(0.5, part.extents[1], 1.0)
        grid = np.array([[x, y, -1.0] for x in xs for y in ys])
        hits, ray_ids, _ = part.ray.intersects_location(
            grid, np.tile([[0.0, 0.0, 1.0]], (len(grid), 1))
        )
        first = np.full(len(grid), np.inf)
        for point, ray in zip(hits, ray_ids, strict=True):
            first[ray] = min(first[ray], point[2])
        assert first.max() == pytest.approx(12 / 2 + 0.25, abs=0.05)
        in_hole = int(np.count_nonzero(first > 1.0))
        assert in_hole == pytest.approx(2 * math.pi * 2.75**2, abs=12)  # two holes' worth


def test_a_part_keeps_its_own_base_when_that_is_the_bigger_flat_face(tmp_path: Path) -> None:
    plate = trimesh.creation.box(extents=(60, 30, 20))
    report = split_mesh(plate, SplitRequest(parts=2, axis="x"), tmp_path)
    assert report.ok
    for part in report.parts:  # the 30 x 30 underside wins over the 30 x 20 cut face
        assert part.extents_mm == [30.0, 30.0, 20.0]


def test_fit_the_bed_cuts_only_the_axes_that_do_not_fit(tmp_path: Path) -> None:
    statue = statuette()
    request = SplitRequest(bed=Bed(x_mm=100, y_mm=100, z_mm=60), margin_mm=5)
    planes = resolve_planes(statue, request)
    assert [p.axis for p in planes] == ["z", "z", "z"]  # 153 mm into 4 x 38.25 under 50
    report = split_mesh(statue, request, tmp_path)
    assert report.ok and len(report.parts) == 4
    assert all(p.fits_bed for p in report.parts)
    assert report.parts[0].extents_mm[2] == pytest.approx(38.25)


def test_a_tilted_plane_and_a_mesh_with_a_hole_in_it(tmp_path: Path) -> None:
    broken = statuette()
    broken.update_faces(np.arange(len(broken.faces)) != 5)  # one triangle missing
    assert not broken.is_watertight
    request = SplitRequest(planes=[CutPlane(point_mm=[0, 0, 70], normal=[0.3, 0, 1])])
    report = split_mesh(broken, request, tmp_path)
    assert report.ok, report.message
    assert report.repaired is not None and report.repaired.printable_after
    assert len(report.parts) == 2 and all(p.dowel_holes == 2 for p in report.parts)
    # refusing the repair refuses the cut
    refused = split_mesh(broken, request.model_copy(update={"repair": False}), tmp_path)
    assert not refused.ok and refused.code == "not_a_volume"


def test_a_cut_face_too_small_for_a_dowel_is_left_without_and_said(tmp_path: Path) -> None:
    rod = trimesh.creation.cylinder(radius=2.0, height=40, sections=32)
    report = split_mesh(rod, SplitRequest(parts=2), tmp_path)
    assert report.ok and len(report.parts) == 2
    assert all(p.dowel_holes == 0 for p in report.parts)
    assert any("too small for a dowel" in w for w in report.warnings)
    # and asking for no connectors is honoured
    plain = split_mesh(
        statuette(), SplitRequest(parts=2, connectors=Connectors(kind="none")), tmp_path
    )
    assert plain.ok and plain.dowels == [] and all(p.dowel_holes == 0 for p in plain.parts)


def test_dowel_spots_sit_deep_inside_the_cut_face() -> None:
    plate = trimesh.creation.box(extents=(80, 20, 10))
    spots, area = dowel_spots(
        plate, np.array([0.0, 0.0, 5.0]), np.array([0.0, 0.0, 1.0]), radius_mm=2.75, count=2
    )
    assert area == pytest.approx(80 * 20)
    assert len(spots) == 2
    for spot in spots:
        assert abs(spot[1]) < 1.0 and spot[2] == pytest.approx(5.0)  # on the centre line
    assert abs(spots[0][0] - spots[1][0]) >= 4 * 2.75  # well apart


def test_a_plane_that_misses_is_an_error_not_a_part(tmp_path: Path) -> None:
    report = split_mesh(
        trimesh.creation.box(extents=(10, 10, 10)),
        SplitRequest(planes=[CutPlane(axis="z", offset_mm=50)]),
        tmp_path,
    )
    assert not report.ok and report.code == "plane_misses"


def test_the_request_needs_something_to_cut_with() -> None:
    with pytest.raises(ValueError):
        SplitRequest()
    with pytest.raises(ValueError):
        CutPlane(axis="x")  # no position
    with pytest.raises(ValueError):
        CutPlane(point_mm=[0, 0, 0], normal=[0, 0, 0])


def test_the_sandboxed_child_returns_the_same_report(tmp_path: Path) -> None:
    source = tmp_path / "statue.stl"
    source.write_bytes(statuette().export(file_type="stl"))
    out = tmp_path / "out"
    direct = split_file(source, "stl", SplitRequest(parts=2), tmp_path / "direct")
    boxed = run_in_sandbox(source, "stl", SplitRequest(parts=2), out)
    assert boxed.ok, boxed.message
    assert [p.model_dump() for p in boxed.parts] == [p.model_dump() for p in direct.parts]
    assert (out / "layout.stl").exists() and (out / "part_02.stl").exists()
