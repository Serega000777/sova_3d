"""F-014/F-015: X3D (.x3d, .x3dv) and VRML97 — Y-up metres in, Z-up millimetres out."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from tests import fixtures
from worker import exporters, sandbox
from worker.importers import web3d
from worker.importers.child import parse
from worker.integrity import CheckStatus
from worker.report import ImportMetadata

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)
DOCTYPE = (
    '<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 3.3//EN" '
    '"http://www.web3d.org/specifications/x3d-3.3.dtd">'
)


def _ifs(mesh: trimesh.Trimesh) -> tuple[str, str]:
    points = ", ".join(" ".join(f"{v:.9g}" for v in row) for row in mesh.vertices)
    index = " ".join(f"{a} {b} {c} -1" for a, b, c in mesh.faces)
    return points, index


def _x3d(scene: str, head: str = "", doctype: str = DOCTYPE) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n{doctype}\n'
        f'<X3D profile="Interchange" version="3.3"><head>{head}</head>'
        f"<Scene>{scene}</Scene></X3D>"
    ).encode()


def _shape(mesh: trimesh.Trimesh, define: str = "") -> str:
    points, index = _ifs(mesh)
    attr = f' DEF="{define}"' if define else ""
    return (
        f'<Shape{attr}><IndexedFaceSet coordIndex="{index}">'
        f'<Coordinate point="{points}"/></IndexedFaceSet></Shape>'
    )


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _size(meta: ImportMetadata) -> tuple[float, ...]:
    bbox = meta.bbox
    assert bbox is not None
    return tuple(round(v, 3) for v in bbox.size)


# --- X3D ----------------------------------------------------------------------------------------


def test_x3d_y_up_metres_become_z_up_millimetres(tmp_path: Path) -> None:
    # 20 mm wide, 10 mm tall (X3D's +Y is up) and 4 mm deep, written in metres
    box = trimesh.creation.box(extents=(0.020, 0.010, 0.004))
    meta = parse("x3d", _write(tmp_path, "box.x3d", _x3d(_shape(box))))
    assert meta.unit_source == "file" and meta.scale_to_mm == pytest.approx(1000.0)
    assert _size(meta) == (20.0, 4.0, 10.0)  # height lands on Z, depth on Y
    assert meta.mesh is not None and meta.mesh.watertight
    assert meta.mesh.volume_mm3 == pytest.approx(20 * 10 * 4, rel=1e-6)
    assert not meta.has_errors


def test_x3d_unit_statement_is_honoured(tmp_path: Path) -> None:
    head = '<unit category="length" name="millimetre" conversionFactor="0.001"/>'
    box = trimesh.creation.box(extents=(20, 10, 4))
    meta = parse("x3d", _write(tmp_path, "mm.x3d", _x3d(_shape(box), head=head)))
    assert meta.scale_to_mm == pytest.approx(1.0)
    assert _size(meta) == (20.0, 4.0, 10.0)


def test_x3d_transforms_and_def_use_place_each_copy(tmp_path: Path) -> None:
    head = '<unit category="length" name="millimetre" conversionFactor="0.001"/>'
    cube = trimesh.creation.box(extents=(10, 10, 10))
    scene = (
        f'<Transform translation="100 0 0">{_shape(cube, define="cube")}</Transform>'
        '<Transform translation="-100 0 0" scale="2 2 2"><Shape USE="cube"/></Transform>'
    )
    meta = parse("x3d", _write(tmp_path, "two.x3d", _x3d(scene, head=head)))
    assert meta.mesh is not None and meta.mesh.bodies == 2
    # the scaled copy is 20 mm, centred at -100; the plain one 10 mm at +100
    assert _size(meta)[0] == pytest.approx(105 + 110)
    assert meta.mesh.volume_mm3 == pytest.approx(1000 + 8000, rel=1e-6)


def test_x3d_rotation_follows_the_spec(tmp_path: Path) -> None:
    head = '<unit category="length" name="millimetre" conversionFactor="0.001"/>'
    box = trimesh.creation.box(extents=(20, 10, 4))
    quarter_turn_about_up = f'<Transform rotation="0 1 0 {math.pi / 2}">{_shape(box)}</Transform>'
    meta = parse("x3d", _write(tmp_path, "rot.x3d", _x3d(quarter_turn_about_up, head=head)))
    # about X3D's up axis, width and depth swap; height is untouched
    assert _size(meta) == (4.0, 20.0, 10.0)


def test_x3d_primitives_are_tessellated_along_y(tmp_path: Path) -> None:
    scene = (
        '<Shape><Box size="0.020 0.010 0.004"/></Shape>'
        '<Transform translation="0.1 0 0"><Shape><Cylinder radius="0.005" height="0.030"/>'
        "</Shape></Transform>"
    )
    meta = parse("x3d", _write(tmp_path, "prims.x3d", _x3d(scene)))
    assert meta.mesh is not None and meta.mesh.bodies == 2
    assert _size(meta)[2] == pytest.approx(30.0, abs=1e-6)  # the cylinder stands upright


def test_x3d_switch_and_lod_render_one_child(tmp_path: Path) -> None:
    small = trimesh.creation.box(extents=(0.001, 0.001, 0.001))
    big = trimesh.creation.box(extents=(0.100, 0.100, 0.100))
    scene = (
        f'<Switch whichChoice="1">{_shape(big)}{_shape(small)}</Switch>'
        f"<LOD>{_shape(small)}{_shape(big)}</LOD>"
    )
    meta = parse("x3d", _write(tmp_path, "pick.x3d", _x3d(scene)))
    assert max(_size(meta)) == pytest.approx(1.0)  # the 100 mm boxes are never drawn


def test_x3d_inline_is_reported_and_never_fetched(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
    scene = f'<Inline url="&quot;file:///etc/passwd&quot;"/>{_shape(box)}'
    meta = parse("x3d", _write(tmp_path, "inline.x3d", _x3d(scene)))
    skipped = [w for w in meta.warnings if w.code == "unsupported_geometry"]
    assert skipped and skipped[0].details["node"] == "Inline"
    assert "passwd" not in str(meta.model_dump())


def test_x3d_internal_dtd_subset_is_refused(tmp_path: Path) -> None:
    laughs = '<!DOCTYPE X3D [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    path = _write(tmp_path, "laughs.x3d", _x3d("<Group/>", doctype=laughs))
    with pytest.raises(ValueError, match="internal subset"):
        parse("x3d", path)


def test_x3d_def_use_amplification_is_refused_before_building(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
    levels = [f'<Group DEF="l0">{_shape(box) * 10}</Group>']
    for n in range(1, 8):  # 10**8 boxes if expanded
        levels.append(f'<Group DEF="l{n}">' + f'<Group USE="l{n - 1}"/>' * 10 + "</Group>")
    path = _write(tmp_path, "bomb.x3d", _x3d("".join(levels)))
    with pytest.raises(ValueError, match="expands past"):
        parse("x3d", path)


def test_x3d_use_cycle_is_refused(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
    scene = f'<Group DEF="g">{_shape(box)}<Group USE="g"/></Group>'
    with pytest.raises(ValueError, match="deeper than"):
        parse("x3d", _write(tmp_path, "cycle.x3d", _x3d(scene)))


def test_an_index_past_the_coordinates_is_refused(tmp_path: Path) -> None:
    scene = (
        '<Shape><IndexedFaceSet coordIndex="0 1 7 -1">'
        '<Coordinate point="0 0 0, 1 0 0, 0 1 0"/></IndexedFaceSet></Shape>'
    )
    with pytest.raises(ValueError, match="past the end"):
        parse("x3d", _write(tmp_path, "oob.x3d", _x3d(scene)))


def test_clockwise_faces_are_flipped(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(0.02, 0.02, 0.02))
    points, index = _ifs(trimesh.Trimesh(box.vertices, box.faces[:, ::-1]))
    scene = (
        f'<Shape><IndexedFaceSet ccw="false" coordIndex="{index}">'
        f'<Coordinate point="{points}"/></IndexedFaceSet></Shape>'
    )
    meta = parse("x3d", _write(tmp_path, "cw.x3d", _x3d(scene)))
    assert meta.mesh is not None and meta.mesh.volume_mm3 == pytest.approx(8000, rel=1e-6)


# --- VRML97 -------------------------------------------------------------------------------------


def _vrml_shape(mesh: trimesh.Trimesh) -> str:
    points, index = _ifs(mesh)
    return (
        "Shape { appearance Appearance { material Material { diffuseColor 1 0 0 } }\n"
        f"  geometry IndexedFaceSet {{ coord Coordinate {{ point [ {points} ] }}\n"
        f"    coordIndex [ {index} ] }} }}"
    )


def test_vrml_scene_graph_is_read(tmp_path: Path) -> None:
    cube = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
    text = (
        "#VRML V2.0 utf8\n# a comment, and commas are whitespace\n"
        "DEF clock TimeSensor { cycleInterval 4 }\n"
        f"Transform {{ translation 0.1, 0, 0 children [ DEF part {_vrml_shape(cube)} ] }}\n"
        "Transform { translation -0.1 0 0 rotation 0 1 0 0 children USE part }\n"
        "ROUTE clock.fraction_changed TO nothing.set_fraction\n"
    )
    meta = parse("wrl", _write(tmp_path, "scene.wrl", text.encode()))
    assert meta.unit_source == "file" and meta.scale_to_mm == pytest.approx(1000.0)
    assert meta.mesh is not None and meta.mesh.bodies == 2
    assert _size(meta) == (210.0, 10.0, 10.0)


def test_vrml_proto_and_vrml1_are_refused(tmp_path: Path) -> None:
    proto = b"#VRML V2.0 utf8\nPROTO Thing [] { Group {} }\n"
    with pytest.raises(ValueError, match="PROTO"):
        parse("wrl", _write(tmp_path, "proto.wrl", proto))
    with pytest.raises(ValueError, match="VRML 1.0"):
        parse("wrl", _write(tmp_path, "old.wrl", b"#VRML V1.0 ascii\nSeparator {}\n"))
    with pytest.raises(ValueError, match="not a VRML97"):
        parse("wrl", _write(tmp_path, "nope.wrl", b"solid cube\nendsolid\n"))


def test_vrml_unclosed_node_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="never closed|ends in the middle"):
        parse("wrl", _write(tmp_path, "open.wrl", b"#VRML V2.0 utf8\nGroup { children [ "))


def test_a_millimetre_file_under_a_metres_spec_is_flagged(tmp_path: Path) -> None:
    # what CAD exporters often do: a 120 mm part written as "120" in a metres-only format
    part = trimesh.creation.box(extents=(120, 60, 40))
    meta = parse(
        "wrl", _write(tmp_path, "cad.wrl", f"#VRML V2.0 utf8\n{_vrml_shape(part)}".encode())
    )
    assert any(w.code == "units_suspicious" for w in meta.warnings)


# --- export -------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["x3d", "x3dv", "wrl"])
def test_export_roundtrips_through_our_own_reader(tmp_path: Path, target: str) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    output = tmp_path / f"box.{target}"
    outcome = exporters.export_mesh(source, "stl", target, output, limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert next(c for c in report.checks if c.id == "volume").status is CheckStatus.passed
    back = parse(target, output)
    assert _size(back) == tuple(fixtures.BOX_MM)  # Z-up mm -> Y-up m -> Z-up mm


def test_exported_files_state_their_conventions(tmp_path: Path) -> None:
    mesh = fixtures.box()
    web3d.write_x3d(mesh, tmp_path / "a.x3d")
    web3d.write_wrl(mesh, tmp_path / "a.wrl")
    web3d.write_x3dv(mesh, tmp_path / "a.x3dv")
    assert (tmp_path / "a.wrl").read_text("utf-8").startswith("#VRML V2.0 utf8")
    assert (tmp_path / "a.x3dv").read_text("utf-8").startswith("#X3D V3.3 utf8\nPROFILE")
    x3d = (tmp_path / "a.x3d").read_text("utf-8")
    assert "<X3D" in x3d and "DOCTYPE" not in x3d
    # metres on disk: the 20 mm side is 0.02
    points = np.array(
        [float(v) for v in x3d.split('point="')[1].split('"')[0].replace(",", " ").split()]
    ).reshape(-1, 3)
    assert np.ptp(points[:, 0]) == pytest.approx(0.020)
    assert np.ptp(points[:, 1]) == pytest.approx(0.005)  # Z-up height is now Y


# --- ElevationGrid and Extrusion --------------------------------------------------------------

MM = '<unit category="length" name="millimetre" conversionFactor="0.001"/>'


def _extrusion(tmp_path: Path, name: str, fields: str) -> ImportMetadata:
    scene = f"<Shape><Extrusion {fields}/></Shape>"
    return parse("x3d", _write(tmp_path, name, _x3d(scene, head=MM)))


def _solid(meta: ImportMetadata) -> float:
    assert meta.mesh is not None and meta.mesh.watertight, meta.warnings
    assert meta.mesh.volume_mm3 > 0  # outward faces: a negative volume means inside-out
    return meta.mesh.volume_mm3


SQUARE = "10 10, 10 -10, -10 -10, -10 10, 10 10"  # clockwise seen from +Y, like the default


@pytest.mark.parametrize("section", [SQUARE, "10 10, -10 10, -10 -10, 10 -10, 10 10"])
def test_a_straight_extrusion_is_a_closed_prism_either_way_round(
    tmp_path: Path, section: str
) -> None:
    meta = _extrusion(tmp_path, "prism.x3d", f'crossSection="{section}" spine="0 0 0, 0 30 0"')
    assert _size(meta) == (20.0, 20.0, 30.0)  # the spine runs up +Y, which is the platform's Z
    assert _solid(meta) == pytest.approx(20 * 20 * 30, rel=1e-9)


def test_a_concave_section_gets_caps_that_stay_inside_it(tmp_path: Path) -> None:
    ell = "0 0, 20 0, 20 5, 5 5, 5 20, 0 20, 0 0"  # an L: area 20*5 + 15*5
    meta = _extrusion(tmp_path, "ell.x3d", f'crossSection="{ell}" spine="0 0 0, 0 10 0"')
    assert _solid(meta) == pytest.approx(175 * 10, rel=1e-9)


def test_scale_per_spine_point_tapers_the_section(tmp_path: Path) -> None:
    meta = _extrusion(
        tmp_path, "taper.x3d", f'crossSection="{SQUARE}" spine="0 0 0, 0 30 0" scale="1 1, 0.5 0.5"'
    )
    frustum = 30 / 3 * (400 + 100 + math.sqrt(400 * 100))
    assert _solid(meta) == pytest.approx(frustum, rel=1e-9)


def test_orientation_turns_the_section_about_the_spine(tmp_path: Path) -> None:
    wide = "20 5, 20 -5, -20 -5, -20 5, 20 5"  # 40 along x, 10 along z
    turned = _extrusion(
        tmp_path,
        "turned.x3d",
        f'crossSection="{wide}" spine="0 0 0, 0 10 0" orientation="0 1 0 {math.pi / 2}"',
    )
    assert _size(turned) == (10.0, 40.0, 10.0)


def test_a_bent_spine_sweeps_a_closed_tube_without_flipping(tmp_path: Path) -> None:
    angles = np.linspace(0.0, math.pi / 2, 13)
    spine = ", ".join(f"{50 * math.cos(a):.9g} {50 * math.sin(a):.9g} 0" for a in angles)
    circle = np.linspace(0.0, 2 * math.pi, 17)
    section = ", ".join(f"{5 * math.cos(a):.9g} {5 * math.sin(a):.9g}" for a in circle)
    meta = _extrusion(tmp_path, "bend.x3d", f'crossSection="{section}" spine="{spine}"')
    polygon = 0.5 * 16 * 25 * math.sin(2 * math.pi / 16)
    assert _solid(meta) == pytest.approx(polygon * 50 * math.pi / 2, rel=0.03)  # Pappus


def test_an_elevation_grid_is_a_height_field_facing_up(tmp_path: Path) -> None:
    grid = (
        '<ElevationGrid xDimension="3" zDimension="2" xSpacing="10" zSpacing="20" '
        'height="0 5 0, 2 8 2"/>'
    )
    path = _write(tmp_path, "terrain.x3d", _x3d(f"<Shape>{grid}</Shape>", head=MM))
    meta = parse("x3d", path)
    assert _size(meta) == (20.0, 20.0, 8.0)  # heights land on Z
    mesh, _, _ = web3d.load_mesh(path, "x3d")
    assert len(mesh.faces) == 4 and (mesh.face_normals[:, 2] > 0).all()
    with pytest.raises(ValueError, match="heights"):
        parse(
            "x3d",
            _write(
                tmp_path,
                "short.x3d",
                _x3d('<Shape><ElevationGrid xDimension="3" zDimension="2" height="0 1"/></Shape>'),
            ),
        )


def test_text_is_still_reported_not_dropped(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(0.01, 0.01, 0.01))
    scene = f'<Shape><Text string="&quot;hi&quot;"/></Shape>{_shape(box)}'
    meta = parse("x3d", _write(tmp_path, "text.x3d", _x3d(scene)))
    assert [w.details["node"] for w in meta.warnings if w.code == "unsupported_geometry"] == [
        "Text"
    ]


# --- X3D ClassicVRML (.x3dv) ------------------------------------------------------------------


def test_x3dv_reads_its_header_statements_and_unit(tmp_path: Path) -> None:
    cube = trimesh.creation.box(extents=(20, 10, 4))
    text = (
        "#X3D V3.3 utf8\n"
        "PROFILE Interchange\n"
        "COMPONENT Geometry3D:2\n"
        'META "generator" "somebody\'s CAD"\n'
        "UNIT length millimetre 0.001\n"
        f"DEF part Transform {{ translation 0 0 0 children [ {_vrml_shape(cube)} ] }}\n"
        "EXPORT part AS thing\n"
    )
    meta = parse("x3dv", _write(tmp_path, "part.x3dv", text.encode()))
    assert meta.scale_to_mm == pytest.approx(1.0) and meta.source_units == "0.001 * meter"
    assert _size(meta) == (20.0, 4.0, 10.0)


def test_x3dv_without_its_header_or_with_a_bad_unit_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ClassicVRML"):
        parse("x3dv", _write(tmp_path, "vrml.x3dv", b"#VRML V2.0 utf8\nGroup {}\n"))
    with pytest.raises(ValueError, match="positive"):
        parse("x3dv", _write(tmp_path, "zero.x3dv", b"#X3D V3.0 utf8\nUNIT length m 0\n"))
