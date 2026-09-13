"""T-018..T-021: importers report units/bbox/mesh stats, scene stats, 3MF objects/build."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import fixtures
from worker import importers, sandbox
from worker.importers.child import parse
from worker.report import ImportMetadata, Severity

FAST = sandbox.SandboxLimits(wall_seconds=60, isolate_network=False)


def codes(meta: ImportMetadata) -> set[str]:
    return {w.code for w in meta.warnings}


def assert_box_mm(meta: ImportMetadata) -> None:
    assert meta.bbox is not None and meta.mesh is not None
    assert tuple(round(s, 6) for s in meta.bbox.size) == fixtures.BOX_MM
    assert meta.mesh.vertices == 8 and meta.mesh.faces == 12 and meta.mesh.bodies == 1
    assert meta.mesh.watertight and meta.mesh.winding_consistent
    assert meta.mesh.volume_mm3 == pytest.approx(1000.0)
    assert meta.mesh.surface_area_mm2 == pytest.approx(2 * (200 + 100 + 50))
    assert meta.mesh.euler_number == 2
    assert meta.mesh.degenerate_faces == 0 and meta.mesh.duplicate_faces == 0


# --- T-018 STL -------------------------------------------------------------------------------


@pytest.mark.parametrize("writer", [fixtures.write_stl_binary, fixtures.write_stl_ascii])
def test_stl_units_bbox_stats(tmp_path: Path, writer) -> None:  # type: ignore[no-untyped-def]
    meta = parse("stl", writer(tmp_path / "box.stl"))
    assert meta.format == "stl" and meta.representation == "mesh"
    assert meta.units == "mm" and meta.unit_source == "assumed" and meta.scale_to_mm == 1.0
    assert_box_mm(meta)
    assert codes(meta) == {"units_assumed"}
    assert not meta.has_errors


def test_stl_open_mesh_is_flagged(tmp_path: Path) -> None:
    meta = parse("stl", fixtures.write_stl_open(tmp_path / "open.stl"))
    assert meta.mesh is not None
    assert not meta.mesh.watertight and meta.mesh.volume_mm3 is None
    assert "not_watertight" in codes(meta)


def test_stl_nan_coordinates_are_an_error(tmp_path: Path) -> None:
    meta = parse("stl", fixtures.write_stl_nan(tmp_path / "nan.stl"))
    assert meta.has_errors
    nan = next(w for w in meta.warnings if w.code == "nan_coordinates")
    assert nan.severity is Severity.error


# --- T-019 OBJ -------------------------------------------------------------------------------


def test_obj_material_refs_are_recorded_not_resolved(tmp_path: Path) -> None:
    meta = parse("obj", fixtures.write_obj_with_materials(tmp_path / "box.obj"))
    assert_box_mm(meta)
    assert meta.material_refs == ["../../etc/passwd.mtl", "steel", "plastic"]
    assert "external_resources_ignored" in codes(meta)
    assert meta.file_metadata["objects"] == "1"
    assert not meta.has_errors


# --- T-020 GLB/glTF --------------------------------------------------------------------------


def test_glb_scene_stats_and_metre_scaling(tmp_path: Path) -> None:
    meta = parse("glb", fixtures.write_glb(tmp_path / "box.glb"))
    assert meta.representation == "scene"
    assert meta.unit_source == "file" and meta.source_units == "meters"
    assert meta.scale_to_mm == 1000.0
    assert meta.scene is not None
    assert meta.scene.meshes == 1 and meta.scene.nodes >= 1
    assert meta.bbox is not None and meta.mesh is not None
    assert tuple(round(s, 3) for s in meta.bbox.size) == (20000.0, 10000.0, 5000.0)
    assert meta.mesh.volume_mm3 == pytest.approx(1000.0 * 1000.0**3)
    assert meta.file_metadata["version"] == "2.0"
    assert not meta.has_errors


def test_gltf_external_buffers_are_not_fetched(tmp_path: Path) -> None:
    meta = parse("gltf", fixtures.write_gltf_external(tmp_path / "ext.gltf"))
    assert "external_resources_ignored" in codes(meta)
    assert meta.scene is not None and meta.scene.meshes == 1
    assert meta.has_errors  # geometry unreadable or empty — never silently fine


def test_glb_rejects_wrong_container(tmp_path: Path) -> None:
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"not a glb at all")
    with pytest.raises(ValueError):
        parse("glb", bad)


# --- T-021 3MF -------------------------------------------------------------------------------


def test_3mf_objects_build_and_units(tmp_path: Path) -> None:
    meta = parse("3mf", fixtures.write_3mf(tmp_path / "box.3mf"))
    assert meta.unit_source == "file" and meta.source_units == "millimeter"
    assert_box_mm(meta)
    assert [o.model_dump() for o in meta.objects] == [
        {"id": "1", "name": "box", "type": "model", "vertices": 8, "triangles": 12}
    ]
    assert [b.model_dump() for b in meta.build_items] == [{"object_id": "1", "has_transform": True}]
    assert meta.file_metadata == {"Title": "Fixture box"}
    assert not meta.has_errors


def test_3mf_inch_units_scale_to_mm(tmp_path: Path) -> None:
    meta = parse(
        "3mf", fixtures.write_3mf(tmp_path / "inch.3mf", fixtures.threemf_model_xml(unit="inch"))
    )
    assert meta.scale_to_mm == 25.4 and meta.bbox is not None
    assert tuple(round(s, 3) for s in meta.bbox.size) == (508.0, 254.0, 127.0)


def test_3mf_empty_build_is_flagged(tmp_path: Path) -> None:
    meta = parse(
        "3mf",
        fixtures.write_3mf(tmp_path / "nobuild.3mf", fixtures.threemf_model_xml(with_build=False)),
    )
    assert "no_build_items" in codes(meta)


@pytest.mark.parametrize(
    ("writer", "message"),
    [
        (fixtures.write_zip_bomb, "compression ratio"),
        (fixtures.write_zip_traversal, "traversal"),
    ],
)
def test_3mf_hostile_archives_rejected(tmp_path: Path, writer, message: str) -> None:  # type: ignore[no-untyped-def]
    from worker.importers.zipsafe import UnsafeArchiveError

    with pytest.raises(UnsafeArchiveError, match=message):
        parse("3mf", writer(tmp_path / "hostile.3mf"))


def test_3mf_xxe_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse("3mf", fixtures.write_3mf_xxe(tmp_path / "xxe.3mf"))


# --- through the sandbox ---------------------------------------------------------------------


def test_import_metadata_runs_in_sandbox(tmp_path: Path) -> None:
    result = importers.import_metadata(
        fixtures.write_stl_binary(tmp_path / "box.stl"), "stl", limits=FAST
    )
    assert result.ok and result.metadata is not None
    assert_box_mm(result.metadata)


def test_import_metadata_surfaces_child_errors(tmp_path: Path) -> None:
    result = importers.import_metadata(
        fixtures.write_zip_bomb(tmp_path / "bomb.3mf"), "3mf", limits=FAST
    )
    assert not result.ok and result.error is not None
    assert result.error.code == "unsafe_archive"

    unsupported = importers.import_metadata(tmp_path / "x.fbx", "fbx", limits=FAST)
    assert unsupported.error is not None and unsupported.error.code == "unsupported_format"

    missing = importers.import_metadata(tmp_path / "missing.stl", "stl", limits=FAST)
    assert missing.error is not None and missing.error.code == "sandbox_crashed"
