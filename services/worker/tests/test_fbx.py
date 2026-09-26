"""F-014/F-015: FBX 7.x, binary and ASCII, read and written without the Autodesk SDK."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
import trimesh

from tests import fixtures
from worker import exporters, sandbox
from worker.importers import fbx
from worker.importers.child import parse
from worker.integrity import CheckStatus
from worker.report import ImportMetadata

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)
N = fbx._Node


def _size(meta: ImportMetadata) -> tuple[float, ...]:
    assert meta.bbox is not None
    return tuple(round(v, 3) for v in meta.bbox.size)


def _p(name: str, *values: object) -> fbx._Node:
    return N("P", [name, name, "", "A", *values])


def _geometry(gid: int, mesh: trimesh.Trimesh) -> fbx._Node:
    index = mesh.faces.astype(np.int64).copy()
    index[:, 2] = -index[:, 2] - 1
    return N(
        "Geometry",
        [np.int64(gid), "g\x00\x01Geometry", "Mesh"],
        [
            N("Vertices", [np.asarray(mesh.vertices, dtype=np.float64).ravel()]),
            N("PolygonVertexIndex", [index.ravel().astype(np.int32)]),
        ],
    )


def _model(mid: int, *props: fbx._Node) -> fbx._Node:
    return N(
        "Model", [np.int64(mid), "m\x00\x01Model", "Mesh"], [N("Properties70", kids=list(props))]
    )


def _binary(
    objects: list[fbx._Node], links: list[tuple[int, int]], settings: list[fbx._Node]
) -> bytes:
    nodes = [
        N("FBXHeaderExtension", kids=[N("FBXVersion", [7400])]),
        N("GlobalSettings", kids=[N("Properties70", kids=settings)]),
        N("Objects", kids=objects),
        N("Connections", kids=[N("C", ["OO", np.int64(a), np.int64(b)]) for a, b in links]),
    ]
    out = bytearray(fbx.BINARY_MAGIC + b"\x1a\x00" + struct.pack("<I", 7400))
    for node in nodes:
        out += fbx._pack_node(node, len(out))
    return bytes(out + b"\x00" * 13)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


CUBE = trimesh.creation.box(extents=(2.0, 2.0, 2.0))  # centred: -1..1 on every axis


def test_centimetres_and_y_up_become_z_up_millimetres(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(2.0, 1.0, 0.4))  # cm, Y-up: 1 cm tall
    data = _binary([_geometry(1, box), _model(2)], [(1, 2), (2, 0)], [])
    meta = parse("fbx", _write(tmp_path, "cm.fbx", data))
    assert meta.scale_to_mm == pytest.approx(10.0) and meta.source_units == "1 * centimeter"
    assert _size(meta) == (20.0, 4.0, 10.0)  # height lands on Z
    assert meta.mesh is not None and meta.mesh.watertight
    assert meta.mesh.volume_mm3 == pytest.approx(20 * 10 * 4)


def test_unit_scale_and_a_z_up_file_are_honoured(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(20.0, 10.0, 4.0))
    settings = [_p("UnitScaleFactor", 0.1), _p("UpAxis", 2), _p("UpAxisSign", 1)]
    meta = parse(
        "fbx",
        _write(tmp_path, "mm.fbx", _binary([_geometry(1, box), _model(2)], [(1, 2)], settings)),
    )
    assert meta.scale_to_mm == pytest.approx(1.0)
    assert _size(meta) == (20.0, 10.0, 4.0)  # already Z-up: nothing turns


def test_the_transform_chain_follows_the_sdk(tmp_path: Path) -> None:
    # parent moves +10 x; child turns 90 deg about Y (the file's up) and scales x by 3
    objects = [
        _geometry(1, CUBE),
        _model(2, _p("Lcl Translation", 10.0, 0.0, 0.0)),
        _model(3, _p("Lcl Rotation", 0.0, 90.0, 0.0), _p("Lcl Scaling", 3.0, 1.0, 1.0)),
    ]
    path = _write(
        tmp_path,
        "chain.fbx",
        _binary(objects, [(1, 3), (3, 2), (2, 0)], [_p("UnitScaleFactor", 0.1)]),
    )
    mesh, scale = fbx.load_mesh(path)
    assert scale == pytest.approx(1.0)
    # 6 wide in x, turned onto the file's z (platform -y); centred on x=10
    np.testing.assert_allclose(mesh.bounds, [[9.0, -3.0, -1.0], [11.0, 3.0, 1.0]], atol=1e-9)


def test_pivots_and_rotation_order_are_applied(tmp_path: Path) -> None:
    # turning about a pivot at x=1 moves the cube's centre from 0 to (1, 0, 1) in file axes
    pivoted = _model(2, _p("RotationPivot", 1.0, 0.0, 0.0), _p("Lcl Rotation", 0.0, 90.0, 0.0))
    path = _write(tmp_path, "pivot.fbx", _binary([_geometry(1, CUBE), pivoted], [(1, 2)], []))
    mesh, _ = fbx.load_mesh(path)
    np.testing.assert_allclose(mesh.bounds.mean(axis=0), [1.0, -1.0, 0.0], atol=1e-9)

    x_then_z = fbx._euler(np.array([90.0, 0.0, 90.0]), 0)
    z_then_x = fbx._euler(np.array([90.0, 0.0, 90.0]), 5)
    assert not np.allclose(x_then_z, z_then_x)  # the order changes where things end up
    np.testing.assert_allclose(x_then_z[:3, :3] @ [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], atol=1e-12)


def test_a_mirroring_scale_keeps_faces_outward(tmp_path: Path) -> None:
    mirrored = _model(2, _p("Lcl Scaling", -1.0, 1.0, 1.0))
    meta = parse(
        "fbx", _write(tmp_path, "mirror.fbx", _binary([_geometry(1, CUBE), mirrored], [(1, 2)], []))
    )
    assert meta.mesh is not None and meta.mesh.volume_mm3 > 0


def test_one_geometry_used_by_two_models_is_placed_twice(tmp_path: Path) -> None:
    objects = [
        _geometry(1, CUBE),
        _model(2, _p("Lcl Translation", -5.0, 0.0, 0.0)),
        _model(3, _p("Lcl Translation", 5.0, 0.0, 0.0)),
    ]
    meta = parse(
        "fbx",
        _write(
            tmp_path, "twice.fbx", _binary(objects, [(1, 2), (1, 3)], [_p("UnitScaleFactor", 0.1)])
        ),
    )
    assert meta.mesh is not None and meta.mesh.bodies == 2
    assert _size(meta) == (12.0, 2.0, 2.0)


def test_ascii_fbx_reads_like_binary(tmp_path: Path) -> None:
    text = """; FBX 7.4.0 project file
; ----------------------------------------------------
FBXHeaderExtension:  {
	FBXHeaderVersion: 1003
	FBXVersion: 7400
}
GlobalSettings:  {
	Version: 1000
	Properties70:  {
		P: "UpAxis", "int", "Integer", "",1
		P: "UnitScaleFactor", "double", "Number", "",0.1
	}
}
Objects:  {
	Geometry: 2035615390896, "Geometry::Cube", "Mesh" {
		Vertices: *24 {
			a: 0,0,0,20,0,0,20,10,0,0,10,0,
			0,0,4,20,0,4,20,10,4,0,10,4
		}
		PolygonVertexIndex: *24 {
			a: 0,3,2,-2,4,5,6,-8,0,1,5,-5,1,2,6,-6,2,3,7,-7,3,0,4,-8
		}
		GeometryVersion: 124
	}
	Model: 2035615390897, "Model::Cube", "Mesh" {
		Version: 232
		Properties70:  {
			P: "Lcl Translation", "Lcl Translation", "", "A",1.5,0,0
		}
		Shading: T
		Culling: "CullingOff"
	}
}
Connections:  {
	;Geometry::Cube, Model::Cube
	C: "OO",2035615390896,2035615390897
	C: "OO",2035615390897,0
}
"""
    meta = parse("fbx", _write(tmp_path, "cube.fbx", text.encode()))
    assert _size(meta) == (20.0, 4.0, 10.0)
    assert (
        meta.mesh is not None
        and meta.mesh.watertight
        and meta.mesh.volume_mm3 == pytest.approx(800)
    )


def test_hostile_and_foreign_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not an FBX"):
        parse("fbx", _write(tmp_path, "stl.fbx", b"solid x\nendsolid x\n"))
    with pytest.raises(ValueError, match="too old"):
        parse(
            "fbx",
            _write(tmp_path, "six.fbx", fbx.BINARY_MAGIC + b"\x1a\x00" + struct.pack("<I", 6100)),
        )
    good = _binary([_geometry(1, CUBE), _model(2)], [(1, 2)], [])
    with pytest.raises(ValueError, match="end"):
        parse("fbx", _write(tmp_path, "cut.fbx", good[: len(good) // 2]))


def test_a_zlib_bomb_stops_at_the_declared_size() -> None:
    header = fbx.BINARY_MAGIC + b"\x1a\x00" + struct.pack("<I", 7400)
    bomb = zlib.compress(b"\x00" * (80 * 1024 * 1024), 9)  # declares 3 doubles, holds 80 MB
    with pytest.raises(ValueError, match="more than its header"):
        fbx._Binary(header + b"d" + struct.pack("<III", 3, 1, len(bomb)) + bomb).value(27)
    with pytest.raises(ValueError, match="larger than"):
        fbx._Binary(header + b"d" + struct.pack("<III", 2**31, 0, 0)).value(27)


def test_a_parent_loop_is_refused(tmp_path: Path) -> None:
    objects = [_geometry(1, CUBE), _model(2), _model(3)]
    data = _binary(objects, [(1, 2), (2, 3), (3, 2)], [])
    with pytest.raises(ValueError, match="deeper"):
        parse("fbx", _write(tmp_path, "loop.fbx", data))


def test_export_roundtrips_and_states_millimetres(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    output = tmp_path / "box.fbx"
    outcome = exporters.export_mesh(source, "stl", "fbx", output, limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None and outcome.report.status is CheckStatus.passed
    assert output.read_bytes().startswith(fbx.BINARY_MAGIC)
    back = parse("fbx", output)
    assert back.scale_to_mm == pytest.approx(1.0)  # UnitScaleFactor 0.1: a unit is a millimetre
    assert _size(back) == tuple(fixtures.BOX_MM)
