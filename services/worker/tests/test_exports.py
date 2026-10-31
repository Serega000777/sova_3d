"""T-023 integrity report, T-024 STL export, T-025 GLB export, T-026 printable gate."""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import trimesh
from lxml import etree
from pydantic import ValidationError

from tests import fixtures
from worker import exporters, sandbox
from worker.importers.child import parse
from worker.importers.common import Z_UP_TO_Y_UP
from worker.integrity import CheckStatus, IntegrityReport, build_report
from worker.report import SceneStats

FAST = sandbox.SandboxLimits(wall_seconds=90, isolate_network=False)


def contracts_dir() -> Path:
    """packages/contracts in the monorepo; absent inside the worker image."""
    root = Path(__file__).resolve()
    for parent in root.parents:
        candidate = parent / "packages" / "contracts"
        if candidate.is_dir():
            return candidate
    pytest.skip("packages/contracts not available (running outside the monorepo)")


def check(report: IntegrityReport, check_id: str) -> CheckStatus:
    return next(c.status for c in report.checks if c.id == check_id)


# --- T-023 -----------------------------------------------------------------------------------


def test_report_has_machine_checks_and_user_summary(tmp_path: Path) -> None:
    source = parse("stl", fixtures.write_stl_binary(tmp_path / "a.stl"))
    output = parse("stl", fixtures.write_stl_ascii(tmp_path / "b.stl"))
    report = build_report(source, output, printable_gate=False)
    assert report.schema_version == 1
    assert report.status is CheckStatus.warned  # STL cannot store units
    assert {c.id for c in report.checks} == {
        "coordinates_finite",
        "bbox_size",
        "surface_area",
        "volume",
        "watertight",
        "face_count",
        "units_explicit",
    }
    assert check(report, "bbox_size") is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.warned
    assert "STL → STL" in report.summary and "units" in report.summary
    assert report.source.volume_mm3 == pytest.approx(1000.0)


def test_report_fails_when_volume_or_watertightness_is_lost(tmp_path: Path) -> None:
    closed = parse("stl", fixtures.write_stl_binary(tmp_path / "closed.stl"))
    opened = parse("stl", fixtures.write_stl_open(tmp_path / "open.stl"))
    report = build_report(closed, opened, printable_gate=False)
    assert report.status is CheckStatus.failed
    assert check(report, "watertight") is CheckStatus.failed
    assert check(report, "volume") is CheckStatus.failed
    assert check(report, "face_count") is CheckStatus.warned
    assert "open edges" in report.summary


def test_report_warns_when_scene_structure_or_animation_is_lost(tmp_path: Path) -> None:
    source = parse("stl", fixtures.write_stl_binary(tmp_path / "source.stl"))
    output = parse("stl", fixtures.write_stl_binary(tmp_path / "output.stl"))
    source = source.model_copy(
        update={
            "representation": "scene",
            "scene": SceneStats(
                nodes=4,
                meshes=2,
                materials=2,
                textures=1,
                animations=1,
                cameras=1,
                lights=2,
            ),
        }
    )

    report = build_report(source, output, printable_gate=False)

    assert report.status is CheckStatus.warned
    for check_id in (
        "scene_node_count",
        "scene_mesh_count",
        "material_count",
        "texture_count",
        "animation_count",
        "camera_count",
        "light_count",
    ):
        assert check(report, check_id) is CheckStatus.warned
    assert report.source.node_count == 4
    assert report.output.node_count is None
    assert "scene node count changed (4 → 0)" in report.summary


def test_report_schema_is_published_to_contracts() -> None:
    """packages/contracts/integrity-report.schema.json must match the pydantic model."""
    expected = IntegrityReport.model_json_schema()
    published = json.loads((contracts_dir() / "integrity-report.schema.json").read_text("utf-8"))
    assert published == expected, "run: uv run python -m worker.integrity --emit-schema"


# --- T-024 / T-025 ---------------------------------------------------------------------------


def test_export_stl_from_obj_is_validated(tmp_path: Path) -> None:
    source = fixtures.write_obj_with_materials(tmp_path / "box.obj")
    outcome = exporters.export_mesh(source, "obj", "stl", tmp_path / "box.stl", limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None and outcome.report.status is CheckStatus.warned
    assert check(outcome.report, "bbox_size") is CheckStatus.passed
    assert check(outcome.report, "volume") is CheckStatus.passed
    assert check(outcome.report, "face_count") is CheckStatus.passed
    assert Path(outcome.output_path or "").stat().st_size > 84


def test_export_glb_scales_mm_to_metres_and_back(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "glb", tmp_path / "box.glb", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert report.output.bbox_size_mm is not None
    assert tuple(round(s, 3) for s in report.output.bbox_size_mm) == fixtures.BOX_MM
    assert check(report, "units_explicit") is CheckStatus.passed
    assert (tmp_path / "box.glb").read_bytes()[:4] == b"glTF"
    # on disk it is what the spec says: metres, and the model's height along +Y
    raw = trimesh.load(tmp_path / "box.glb", force="mesh", process=False)
    width, depth, height = fixtures.BOX_MM
    np.testing.assert_allclose(raw.extents, (width / 1000, height / 1000, depth / 1000))


def test_export_glb_to_stl_roundtrip(tmp_path: Path) -> None:
    source = fixtures.write_glb(tmp_path / "box.glb")
    outcome = exporters.export_mesh(source, "glb", "stl", tmp_path / "box.stl", limits=FAST)
    assert outcome.ok, outcome
    assert outcome.report is not None
    assert outcome.report.source.bbox_size_mm is not None
    assert tuple(round(s, 3) for s in outcome.report.source.bbox_size_mm) == (
        20000.0,
        5000.0,  # glTF's Y is up: it becomes the platform's Z
        10000.0,
    )
    assert check(outcome.report, "bbox_size") is CheckStatus.passed


def test_scene_export_applies_world_transforms_and_instances(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    output = tmp_path / "assembly.stl"
    identity = np.eye(4)
    moved = np.eye(4)
    moved[0, 3] = 25
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="original",
                path=str(source),
                format="stl",
                name="Original",
                world_transform=identity.tolist(),
            ),
            exporters.SceneMeshInput(
                node_id="instance",
                path=str(source),
                format="stl",
                name="Instance",
                world_transform=moved.tolist(),
            ),
        ],
        "stl",
        output,
        limits=FAST,
    )
    assert outcome.ok, outcome.error
    made = trimesh.load(output, file_type="stl", force="mesh")
    assert isinstance(made, trimesh.Trimesh)
    np.testing.assert_allclose(made.bounds, [[-10, -5, -2.5], [35, 5, 2.5]])
    assert made.volume == pytest.approx(2000)


def test_scene_glb_preserves_named_objects_and_pbr_appearance(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    texture = tmp_path / "tile.png"
    from PIL import Image

    Image.new("RGB", (4, 4), (180, 120, 70)).save(texture)
    texture_hash = __import__("hashlib").sha256(texture.read_bytes()).hexdigest()
    solid = {
        "schema_version": 1,
        "catalog_material_id": "interior.paint.warm-white-matte.v1",
        "base_color": "#F2EBDD",
        "gloss_pct": 8,
        "roughness": 0.92,
        "texture_sha256": None,
        "texture_tile_size_mm": None,
    }
    textured = {
        "schema_version": 1,
        "catalog_material_id": "interior.wood.test.v1",
        "base_color": "#B47846",
        "gloss_pct": 24,
        "roughness": 0.76,
        "texture_sha256": texture_hash,
        "texture_tile_size_mm": 100.0,
    }
    output = tmp_path / "materials.glb"
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="wall",
                path=str(source),
                format="stl",
                name="Wall",
                world_transform=np.eye(4).tolist(),
                appearance=solid,
            ),
            exporters.SceneMeshInput(
                node_id="chair",
                path=str(source),
                format="stl",
                name="Chair",
                world_transform=np.eye(4).tolist(),
                appearance=textured,
                texture_path=str(texture),
            ),
        ],
        "glb",
        output,
        limits=FAST,
    )
    assert outcome.ok, outcome.error
    scene = trimesh.load(output, file_type="glb", force="scene", process=False)
    assert isinstance(scene, trimesh.Scene)
    assert set(scene.geometry) == {"Wall", "Chair"}
    materials = {name: geometry.visual.material for name, geometry in scene.geometry.items()}
    assert materials["Wall"].name == "interior.paint.warm-white-matte.v1"
    assert materials["Wall"].roughnessFactor == pytest.approx(0.92)
    assert materials["Chair"].name == "interior.wood.test.v1"
    assert materials["Chair"].baseColorTexture is not None
    assert scene.geometry["Chair"].visual.uv is not None
    assert outcome.report is not None
    assert outcome.report.output.material_count == 2
    assert outcome.report.output.texture_count == 1
    assert check(outcome.report, "material_count") is CheckStatus.passed
    assert check(outcome.report, "texture_count") is CheckStatus.passed


def test_scene_glb_keeps_duplicate_display_names_as_distinct_nodes(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    output = tmp_path / "duplicates.glb"
    second_transform = np.eye(4)
    second_transform[0, 3] = 40.0
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="chair_a",
                path=str(source),
                format="stl",
                name="Chair",
                world_transform=np.eye(4).tolist(),
            ),
            exporters.SceneMeshInput(
                node_id="chair_b",
                path=str(source),
                format="stl",
                name="Chair",
                world_transform=second_transform.tolist(),
            ),
        ],
        "glb",
        output,
        limits=FAST,
    )
    assert outcome.ok, outcome.error
    scene = trimesh.load(output, file_type="glb", force="scene", process=False)
    assert isinstance(scene, trimesh.Scene)
    assert set(scene.geometry) == {"Chair", "Chair [chair_b]"}
    assert len(scene.graph.nodes_geometry) == 2
    np.testing.assert_allclose(scene.bounds[:, 0], [-0.01, 0.05], atol=1e-9)


def test_scene_glb_embeds_the_trusted_revolute_joint_animation(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    output = tmp_path / "hinge.glb"
    lid_transform = np.eye(4)
    lid_transform[2, 3] = 10.0
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="base",
                path=str(source),
                format="stl",
                name="Base",
                world_transform=np.eye(4).tolist(),
            ),
            exporters.SceneMeshInput(
                node_id="lid",
                path=str(source),
                format="stl",
                name="Lid",
                world_transform=lid_transform.tolist(),
            ),
        ],
        "glb",
        output,
        animation=exporters.SceneAnimationInput(
            node_id="lid",
            axis="x",
            min_angle_deg=0,
            max_angle_deg=110,
        ),
        limits=FAST,
    )
    assert outcome.ok, outcome.error
    metadata = parse("glb", output)
    assert metadata.scene is not None and metadata.scene.animations == 1

    data = output.read_bytes()
    json_length, json_kind = struct.unpack_from("<I4s", data, 12)
    assert json_kind == b"JSON"
    document = json.loads(data[20 : 20 + json_length].rstrip(b" \0"))
    animation = document["animations"][0]
    target = animation["channels"][0]["target"]
    assert target["path"] == "rotation"
    animated_node = document["nodes"][target["node"]]
    assert animated_node["name"] == "Lid"
    assert "matrix" not in animated_node
    assert animated_node["scale"] == pytest.approx([0.001, 0.001, 0.001])
    assert animation["samplers"][0]["interpolation"] == "LINEAR"


def _glb_document(data: bytes) -> tuple[dict[str, Any], bytes]:
    json_length, json_kind = struct.unpack_from("<I4s", data, 12)
    assert json_kind == b"JSON"
    document = json.loads(data[20 : 20 + json_length].rstrip(b" \0"))
    offset = 20 + json_length
    binary_length, binary_kind = struct.unpack_from("<I4s", data, offset)
    assert binary_kind == b"BIN\0"
    return document, data[offset + 8 : offset + 8 + binary_length]


@pytest.mark.parametrize("turned", [False, True])
def test_scene_glb_embeds_the_trusted_prismatic_joint_in_metres_y_up(
    tmp_path: Path, turned: bool
) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    output = tmp_path / "slide.glb"
    # a user may later turn the whole mechanism group; the slide follows the guides
    lid_transform = np.eye(4)
    if turned:  # 90 degrees about platform Z
        lid_transform[:2, :2] = [[0.0, -1.0], [1.0, 0.0]]
    lid_transform[:3, 3] = [0.0, 3.3, 30.0]
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="base",
                path=str(source),
                format="stl",
                name="Base",
                world_transform=np.eye(4).tolist(),
            ),
            exporters.SceneMeshInput(
                node_id="lid",
                path=str(source),
                format="stl",
                name="Lid",
                world_transform=lid_transform.tolist(),
            ),
        ],
        "glb",
        output,
        animation=exporters.SceneAnimationInput(
            kind="prismatic", node_id="lid", axis="y", min_travel_mm=0, max_travel_mm=55
        ),
        limits=FAST,
    )
    assert outcome.ok, outcome.error
    metadata = parse("glb", output)
    assert metadata.scene is not None and metadata.scene.animations == 1

    document, binary = _glb_document(output.read_bytes())
    (animation,) = document["animations"]
    assert animation["name"] == "SlidingLid"
    (channel,) = animation["channels"]
    assert channel["target"]["path"] == "translation"
    node = document["nodes"][channel["target"]["node"]]
    assert node["name"] == "Lid" and "matrix" not in node
    accessor = document["accessors"][animation["samplers"][0]["output"]]
    assert accessor["type"] == "VEC3" and accessor["count"] == 2
    view = document["bufferViews"][accessor["bufferView"]]
    start = view["byteOffset"]
    keys = np.frombuffer(binary[start : start + view["byteLength"]], dtype="<f4").reshape(2, 3)

    # Exactly what the Studio preview applies: the world matrix times a local +Y travel in
    # platform mm, then mm -> m and Z-up -> Y-up. Platform +Y is glTF -Z.
    def gltf(travel: float) -> np.ndarray:
        slide = np.eye(4)
        slide[1, 3] = travel
        moved = lid_transform @ slide
        scale = np.diag([0.001, 0.001, 0.001, 1.0])
        return (np.asarray(Z_UP_TO_Y_UP) @ scale @ moved)[:3, 3]

    np.testing.assert_allclose(keys[0], gltf(0), atol=1e-7)
    np.testing.assert_allclose(keys[1], gltf(55), atol=1e-7)
    expected_delta = [-0.055, 0, 0] if turned else [0, 0, -0.055]
    np.testing.assert_allclose(keys[1] - keys[0], expected_delta, atol=1e-7)
    np.testing.assert_allclose(node["translation"], keys[0], atol=1e-7)


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "prismatic", "min_angle_deg": 0, "max_angle_deg": 10},
        {"kind": "prismatic", "min_travel_mm": 0},
        {"kind": "prismatic", "min_travel_mm": 5, "max_travel_mm": 5},
        {"min_angle_deg": 0, "max_angle_deg": 90, "min_travel_mm": 0, "max_travel_mm": 5},
        {"kind": "screw", "min_travel_mm": 0, "max_travel_mm": 5},
    ],
)
def test_scene_animation_rejects_malformed_joint_ranges(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        exporters.SceneAnimationInput(node_id="lid", axis="y", **fields)


def test_glb_to_glb_preserves_the_complete_scene_container_exactly(tmp_path: Path) -> None:
    mesh = fixtures.write_stl_binary(tmp_path / "part.stl")
    source = tmp_path / "source.glb"
    moved = np.eye(4)
    moved[2, 3] = 10.0
    built = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="base",
                path=str(mesh),
                format="stl",
                name="Base",
                world_transform=np.eye(4).tolist(),
            ),
            exporters.SceneMeshInput(
                node_id="lid",
                path=str(mesh),
                format="stl",
                name="Lid",
                world_transform=moved.tolist(),
            ),
        ],
        "glb",
        source,
        animation=exporters.SceneAnimationInput(
            node_id="lid",
            axis="x",
            min_angle_deg=0,
            max_angle_deg=90,
        ),
        limits=FAST,
    )
    assert built.ok, built.error

    copied = tmp_path / "copied.glb"
    outcome = exporters.export_mesh(source, "glb", "glb", copied, limits=FAST)

    assert outcome.ok, outcome.error
    assert copied.read_bytes() == source.read_bytes()
    assert outcome.report is not None and outcome.report.status is CheckStatus.passed
    assert check(outcome.report, "scene_node_count") is CheckStatus.passed
    assert check(outcome.report, "scene_mesh_count") is CheckStatus.passed
    assert check(outcome.report, "animation_count") is CheckStatus.passed
    assert outcome.report.source.animation_count == 1
    assert outcome.report.output.animation_count == 1


def test_scene_animation_fails_closed_when_its_node_is_hidden(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "part.stl")
    outcome = exporters.export_scene(
        [
            exporters.SceneMeshInput(
                node_id="base",
                path=str(source),
                format="stl",
                name="Base",
                world_transform=np.eye(4).tolist(),
            )
        ],
        "glb",
        tmp_path / "bad.glb",
        animation=exporters.SceneAnimationInput(
            node_id="hidden_lid",
            axis="x",
            min_angle_deg=0,
            max_angle_deg=110,
        ),
        limits=FAST,
    )
    assert not outcome.ok and outcome.error is not None
    assert outcome.error.code == "convert_failed"


def test_box_projection_uses_dominant_axis_and_local_millimetres() -> None:
    mesh = trimesh.Trimesh(
        vertices=[[10, 20, 30], [10, 120, 30], [10, 20, 230]],
        faces=[[0, 1, 2]],
        process=False,
    )
    uv = exporters._box_project_uv(mesh, 100.0)
    np.testing.assert_allclose(uv, [[0.2, 0.3], [1.2, 0.3], [0.2, 2.3]])


def test_export_rejects_unsupported_target_and_bad_source(tmp_path: Path) -> None:
    unsupported = exporters.export_mesh(
        tmp_path / "x.stl", "stl", "gltf", tmp_path / "x.gltf", limits=FAST
    )
    assert not unsupported.ok and unsupported.error is not None
    assert unsupported.error.code == "unsupported_target"

    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"garbage")
    outcome = exporters.export_mesh(bad, "glb", "stl", tmp_path / "out.stl", limits=FAST)
    assert not outcome.ok and outcome.error is not None
    assert outcome.error.code == "convert_failed"
    assert not (tmp_path / "out.stl").exists()


# --- T-026 -----------------------------------------------------------------------------------


def test_printable_gate_blocks_open_mesh(tmp_path: Path) -> None:
    source = fixtures.write_stl_open(tmp_path / "open.stl")
    outcome = exporters.export_mesh(
        source, "stl", "stl", tmp_path / "print.stl", printable_gate=True, limits=FAST
    )
    assert not outcome.ok and outcome.error is None
    report = outcome.report
    assert report is not None and report.status is CheckStatus.failed
    assert check(report, "printable_topology") is CheckStatus.failed
    assert "Not print-ready" in report.summary and "Repair" in report.summary
    assert not (tmp_path / "print.stl").exists()  # never hand out a red file


def test_printable_gate_passes_manifold_mesh(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(
        source, "stl", "stl", tmp_path / "print.stl", printable_gate=True, limits=FAST
    )
    assert outcome.ok and outcome.report is not None
    assert check(outcome.report, "printable_topology") is CheckStatus.passed
    assert outcome.report.printable_gate is True


def test_export_3mf_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(
        source, "stl", "3mf", tmp_path / "box.3mf", printable_gate=True, limits=FAST
    )
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # 3MF carries units
    assert check(report, "printable_topology") is CheckStatus.passed
    assert check(report, "volume") is CheckStatus.passed
    assert (tmp_path / "box.3mf").read_bytes()[:2] == b"PK"
    with zipfile.ZipFile(tmp_path / "box.3mf") as archive:
        model = etree.fromstring(archive.read("3D/3dmodel.model"))
    namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    assert model.find(f"{namespace}resources/{namespace}basematerials") is None


def test_export_dae_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "dae", tmp_path / "box.dae", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # our own <unit> tag
    assert check(report, "volume") is CheckStatus.passed
    text = (tmp_path / "box.dae").read_text("utf-8")
    assert '<unit meter="0.001" name="millimeter"/>' in text
    assert "<up_axis>Z_UP</up_axis>" in text  # the data is Z-up; trimesh's own tag lies


def test_export_usdz_declares_units_and_roundtrips(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    outcome = exporters.export_mesh(source, "stl", "usdz", tmp_path / "box.usdz", limits=FAST)
    assert outcome.ok, outcome
    report = outcome.report
    assert report is not None and report.status is CheckStatus.passed
    assert check(report, "units_explicit") is CheckStatus.passed  # our own stage sets it
    assert check(report, "volume") is CheckStatus.passed
    assert (tmp_path / "box.usdz").read_bytes()[:2] == b"PK"  # a ZIP container
