"""F-077: a game-ready GLB — metres, +Y up, base pivot, LODs, UVs, PBR material, a collider."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from tests import fixtures
from worker import gameready, sandbox
from worker.gameready import GameRequest
from worker.importers.common import Z_UP_TO_Y_UP

FAST = sandbox.SandboxLimits(wall_seconds=120, cpu_seconds=120, isolate_network=False)


def _ball() -> trimesh.Trimesh:
    ball = trimesh.creation.icosphere(subdivisions=5, radius=40.0)  # 20480 triangles, mm
    ball.apply_translation((100.0, 100.0, 40.0))  # standing on the bed, far from the origin
    return cast(trimesh.Trimesh, ball)


def _mesh(scene: trimesh.Scene, name: str) -> trimesh.Trimesh:
    return cast(trimesh.Trimesh, scene.geometry[name])


def _world_mesh(scene: trimesh.Scene, name: str) -> trimesh.Trimesh:
    mesh = _mesh(scene, name).copy()
    transform, _ = scene.graph.get(frame_to=name)
    mesh.apply_transform(transform)
    return mesh


def _glb_document(data: bytes) -> dict[str, Any]:
    json_length, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    return cast(dict[str, Any], json.loads(data[20 : 20 + json_length].rstrip(b" \0")))


def test_the_asset_is_metres_y_up_and_stands_on_its_pivot() -> None:
    scene, report = gameready.build(_ball(), GameRequest(name="Ball", max_triangles=5000))
    lod0 = _mesh(scene, "Ball_LOD0")
    np.testing.assert_allclose(lod0.bounds, [[-0.04, 0.0, -0.04], [0.04, 0.08, 0.04]], atol=5e-4)
    assert report.size_m == pytest.approx((0.08, 0.08, 0.08), abs=5e-4)
    tall = trimesh.creation.box(extents=(10.0, 20.0, 100.0))  # 100 mm tall on the platform
    tall_scene, _ = gameready.build(tall, GameRequest(pivot="centre", lod_ratios=[]))
    np.testing.assert_allclose(_mesh(tall_scene, "Model_LOD0").extents, (0.01, 0.1, 0.02))
    np.testing.assert_allclose(_mesh(tall_scene, "Model_LOD0").bounds.mean(axis=0), 0, atol=1e-9)


def test_lods_meet_their_budgets_and_say_how_far_they_stray() -> None:
    scene, report = gameready.build(
        _ball(), GameRequest(name="Ball", max_triangles=5000, lod_ratios=[0.5, 0.2])
    )
    assert [lod.name for lod in report.lods] == ["Ball_LOD0", "Ball_LOD1", "Ball_LOD2"]
    assert [lod.triangles for lod in report.lods] == [5000, 2500, 1000]
    assert report.lods[0].max_deviation_mm == 0
    assert 0 < report.lods[1].max_deviation_mm < report.lods[2].max_deviation_mm < 3.0
    for lod in report.lods:
        shell = _mesh(scene, lod.name).copy()
        shell.merge_vertices(merge_tex=True, merge_norm=True)  # UV seams split vertices
        assert shell.is_watertight  # decimation keeps the shell closed


def test_a_small_model_is_not_padded_to_the_budget_nor_crushed_into_a_sheet() -> None:
    cube = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    scene, report = gameready.build(cube, GameRequest(max_triangles=5000))
    assert report.lods[0].triangles == 12 and report.triangles_in == 12
    assert [lod.triangles for lod in report.lods] == [12, 12, 12]  # nothing left to remove
    for lod in report.lods:
        np.testing.assert_allclose(_mesh(scene, lod.name).extents, (0.02, 0.02, 0.02))


def test_the_collider_is_convex_and_engine_sized() -> None:
    scene, report = gameready.build(_ball(), GameRequest(name="Ball"))
    assert report.collider is not None and report.collider.name == "UCX_Ball_00"
    collider = _mesh(scene, "UCX_Ball_00")
    assert len(collider.faces) <= gameready.MAX_COLLIDER_TRIANGLES
    assert collider.is_convex and collider.is_watertight
    assert report.collider.triangle_limit == gameready.MAX_COLLIDER_TRIANGLES
    assert report.collider.is_convex is True
    assert report.collider.is_watertight is True
    assert report.collider.volume_ratio_pct == pytest.approx(
        collider.volume / _mesh(scene, "Ball_LOD0").volume * 100, abs=0.01
    )
    assert report.collider.floor_offset_mm == pytest.approx(collider.bounds[0][1] * 1000, abs=0.001)
    lod0 = _mesh(scene, "Ball_LOD0")
    # Decimation may slightly under-approximate the render mesh; the report exposes that
    # ratio instead of claiming this bounded hull is an exact containment proof.
    assert collider.volume >= lod0.volume * 0.9

    _, boxed = gameready.build(_ball(), GameRequest(collider="box"))
    assert boxed.collider is not None and boxed.collider.triangles == 12
    assert boxed.collider.is_convex and boxed.collider.is_watertight
    assert boxed.collider.volume_ratio_pct is not None and boxed.collider.volume_ratio_pct > 100
    no_scene, none = gameready.build(_ball(), GameRequest(collider="none"))
    assert none.collider is None and not any(n.startswith("UCX_") for n in no_scene.geometry)


def test_uvs_and_a_pbr_material_come_with_every_lod(tmp_path: Path) -> None:
    red = GameRequest(name="Ball", base_color=(1.0, 0.0, 0.0, 1.0), roughness=0.3)
    scene, report = gameready.build(_ball(), red)
    assert [atlas.lod for atlas in report.uv_atlases] == ["Ball_LOD0", "Ball_LOD1", "Ball_LOD2"]
    for atlas in report.uv_atlases:
        assert 0 < atlas.triangle_area_pct <= 100
        assert atlas.degenerate_triangles == 0
        assert atlas.out_of_bounds_vertices == 0
    path = tmp_path / "ball.glb"
    path.write_bytes(scene.export(file_type="glb"))  # type: ignore[no-untyped-call]
    back = cast(trimesh.Scene, trimesh.load(path))
    for name in ("Ball_LOD0", "Ball_LOD1", "Ball_LOD2"):
        geometry = _mesh(back, name)
        visual = geometry.visual
        assert isinstance(visual, trimesh.visual.TextureVisuals)
        assert visual.uv is not None and len(visual.uv) == len(geometry.vertices)
        assert ((visual.uv >= -1e-6) & (visual.uv <= 1 + 1e-6)).all()  # one packed atlas
        material: Any = visual.material
        assert list(material.baseColorFactor) == [255, 0, 0, 255]
        assert material.roughnessFactor == pytest.approx(0.3)


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "has space"},
        {"lod_ratios": [0.2, 0.5]},  # not heaviest first
        {"lod_ratios": [1.5]},
        {"max_triangles": 10},
        {"base_color": (2.0, 0.0, 0.0, 1.0)},
    ],
)
def test_nonsense_requests_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GameRequest.model_validate(bad)


def test_the_sandboxed_export_reads_a_file_and_writes_one(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "box.stl")
    output = tmp_path / "box_game.glb"
    report = gameready.run_in_sandbox(source, "stl", GameRequest(name="Crate"), output, FAST)
    assert report.ok, report.message
    assert report.file_bytes == output.stat().st_size > 0
    back = trimesh.load(output)
    width, depth, height = fixtures.BOX_MM
    np.testing.assert_allclose(
        _mesh(cast(trimesh.Scene, back), "Crate_LOD0").extents,
        np.asarray((width / 1000, height / 1000, depth / 1000)),
    )


def _painted_ball() -> tuple[trimesh.Trimesh, np.ndarray]:
    ball = _ball()
    colours = np.tile(np.array([[30, 60, 220, 255]], dtype=np.uint8), (len(ball.faces), 1))
    colours[ball.triangles_center[:, 2] > 40.0] = (220, 30, 30, 255)  # red cap, blue base
    return ball, colours


def _texel(visual: trimesh.visual.TextureVisuals, uv: np.ndarray) -> np.ndarray:
    material: Any = visual.material
    image = np.asarray(material.baseColorTexture.convert("RGBA"))
    size = image.shape[0]
    x = np.clip(np.round(uv[:, 0] * (size - 1)).astype(int), 0, size - 1)
    y = np.clip(np.round((1 - uv[:, 1]) * (size - 1)).astype(int), 0, size - 1)
    texels: np.ndarray = image[y, x]
    return texels


def test_paint_is_baked_into_every_lods_texture(tmp_path: Path) -> None:
    ball, colours = _painted_ball()
    scene, report = gameready.build(ball, GameRequest(name="Ball", texture_px=512), colours)
    assert report.baked_texture_px == 512
    path = tmp_path / "ball.glb"
    path.write_bytes(scene.export(file_type="glb"))  # type: ignore[no-untyped-call]
    back = cast(trimesh.Scene, trimesh.load(path))
    for name in ("Ball_LOD0", "Ball_LOD1", "Ball_LOD2"):
        lod = _mesh(back, name)
        visual = lod.visual
        assert isinstance(visual, trimesh.visual.TextureVisuals)
        centres = visual.uv[lod.faces].mean(axis=1)  # each face's own UV triangle
        texels = _texel(visual, centres)
        red = texels[:, 0] > 150
        # glTF is Y-up: the cap that was on top (platform +Z) is now along +Y
        up = lod.triangles_center[:, 1] > 0.04 + 0.002
        down = lod.triangles_center[:, 1] < 0.04 - 0.002
        assert red[up].mean() > 0.97 and (~red[down]).mean() > 0.97, name


def test_an_unpainted_model_bakes_nothing() -> None:
    _, report = gameready.build(_ball(), GameRequest())
    assert report.baked_texture_px is None
    ball, colours = _painted_ball()
    _, plain = gameready.build(ball, GameRequest(uv=False), colours)
    assert plain.baked_texture_px is None  # no UVs, nowhere to bake to
    assert plain.uv_atlases == []


# --- F-002 scan quality: bake_mesh_texture honestly reports what it could and couldn't do -----


def test_bake_mesh_texture_is_honest_without_colour_data() -> None:
    """The common case for a scan: an STL round-trip carries no colour at all."""
    texture, report = gameready.bake_mesh_texture(_ball(), 512)
    assert texture is None
    assert report == {"texture_baked": False, "reason": "no_color_data"}


def test_bake_mesh_texture_bakes_a_painted_meshs_colours() -> None:
    ball, colours = _painted_ball()
    painted = ball.copy()
    painted.visual = trimesh.visual.ColorVisuals(mesh=painted, face_colors=colours)
    texture, report = gameready.bake_mesh_texture(painted, 256)
    assert texture is not None
    assert texture.size == (256, 256)
    assert report == {"texture_baked": True, "texture_size": 256}


def test_scan_photo_colours_survive_repair_transfer_and_glb_atlas(tmp_path: Path) -> None:
    source, colours = _painted_ball()
    source.visual = trimesh.visual.ColorVisuals(mesh=source, face_colors=colours)
    repaired = source.copy()
    repaired.apply_scale(0.98)  # type: ignore[no-untyped-call]
    transferred = gameready.transfer_face_colours(repaired, source)
    assert transferred is not None
    repaired.visual = trimesh.visual.ColorVisuals(mesh=repaired, face_colors=transferred)

    output = tmp_path / "scan.glb"
    report = gameready.export_textured_scan_glb(repaired, 256, output)
    assert report["texture_baked"] is True
    assert output.read_bytes()[:4] == b"glTF"
    loaded = cast(trimesh.Scene, trimesh.load(output))
    mesh = cast(trimesh.Trimesh, next(iter(loaded.geometry.values())))
    assert isinstance(mesh.visual, trimesh.visual.TextureVisuals)
    np.testing.assert_allclose(mesh.extents, repaired.extents[[0, 2, 1]] * 0.001, rtol=1e-4)


def test_a_painted_glb_keeps_its_colours_through_the_sandboxed_export(tmp_path: Path) -> None:
    ball, colours = _painted_ball()
    painted = ball.copy()
    painted.unmerge_vertices()  # what worker.paint writes: every face its own vertices
    painted.visual = trimesh.visual.ColorVisuals(mesh=painted, face_colors=colours)
    painted.apply_scale(0.001)  # type: ignore[no-untyped-call]
    painted.apply_transform(Z_UP_TO_Y_UP)
    source = tmp_path / "painted.glb"
    source.write_bytes(
        trimesh.Scene(painted).export(file_type="glb")  # type: ignore[no-untyped-call]
    )
    output = tmp_path / "game.glb"
    report = gameready.run_in_sandbox(source, "glb", GameRequest(name="Ball"), output, FAST)
    assert report.ok, report.message
    assert report.baked_texture_px == 1024
    lod0 = _mesh(cast(trimesh.Scene, trimesh.load(output)), "Ball_LOD0")
    assert isinstance(lod0.visual, trimesh.visual.TextureVisuals)
    texels = _texel(lod0.visual, lod0.visual.uv[lod0.faces].mean(axis=1))
    top = lod0.triangles_center[:, 1] > 0.045
    assert (texels[top][:, 0] > 150).mean() > 0.97


# --- Reference 83/84/86: scene-preserving game-ready export — every object its own LOD/UV/collider


def _world_box(x_mm: float) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=fixtures.BOX_MM)
    box.apply_translation((x_mm, 0.0, 0.0))  # type: ignore[no-untyped-call]
    return cast(trimesh.Trimesh, box)


def test_build_scene_keeps_every_objects_own_lod_uv_and_collider() -> None:
    objects = [
        ("node_a", "First", _world_box(0.0), None, np.zeros(3)),
        ("node_b", "Second", _world_box(200.0), None, np.zeros(3)),
    ]
    scene, report = gameready.build_scene(objects, GameRequest(lod_ratios=[0.5]))
    assert report.ok, report.message
    assert report.objects == 2
    assert report.triangles_in == 24  # two boxes, 12 triangles each
    assert {entry.node_id for entry in report.per_object} == {"node_a", "node_b"}
    assert {entry.source_name for entry in report.per_object} == {"First", "Second"}
    for entry in report.per_object:
        assert entry.report.ok
        assert len(entry.report.lods) == 2  # LOD0 + one requested ratio
        collider_name = f"UCX_{entry.name}_00"
        assert collider_name in scene.geometry
        assert any(name.startswith(f"{entry.name}_LOD") for name in scene.geometry)


def test_build_scene_preserves_relative_world_placement() -> None:
    objects = [
        ("node_a", "First", _world_box(0.0), None, np.zeros(3)),
        ("node_b", "Second", _world_box(0.0), None, np.asarray((200.0, 0.0, 0.0))),
    ]
    scene, report = gameready.build_scene(objects, GameRequest(pivot="centre"))
    first = _world_mesh(scene, f"{report.per_object[0].name}_LOD0")
    second = _world_mesh(scene, f"{report.per_object[1].name}_LOD0")
    # platform X stays glTF X; the 200 mm world offset becomes 0.2 m, not each object's own origin
    offset = second.bounds.mean(axis=0)[0] - first.bounds.mean(axis=0)[0]
    assert offset == pytest.approx(0.2, abs=1e-6)


def test_build_scene_disambiguates_colliding_sanitized_names() -> None:
    objects = [
        ("node_a", f"Part{'x' * 50}!!", _world_box(0.0), None, np.zeros(3)),
        ("node_b", f"Part{'x' * 50}??", _world_box(50.0), None, np.zeros(3)),
    ]
    _, report = gameready.build_scene(objects, GameRequest())
    names = [entry.name for entry in report.per_object]
    assert len(set(names)) == 2


def test_build_scene_refuses_an_empty_object_list() -> None:
    _, report = gameready.build_scene([], GameRequest())
    assert not report.ok and report.message


def test_scene_game_report_rejects_a_forged_aggregate() -> None:
    object_report = gameready.ObjectGameReport(
        node_id="node_a",
        source_name="First",
        name="First",
        report=gameready.GameReport(ok=True, triangles_in=12),
    )
    with pytest.raises(ValidationError):
        gameready.SceneGameReport(ok=True, objects=1, triangles_in=999, per_object=[object_report])
    with pytest.raises(ValidationError):
        gameready.SceneGameReport(ok=True, objects=2, triangles_in=12, per_object=[object_report])
    duplicate = gameready.ObjectGameReport(
        node_id="node_a",
        source_name="Dup",
        name="Dup",
        report=gameready.GameReport(ok=True, triangles_in=12),
    )
    with pytest.raises(ValidationError):
        gameready.SceneGameReport(
            ok=True, objects=2, triangles_in=24, per_object=[object_report, duplicate]
        )


def test_the_sandboxed_scene_export_combines_two_objects_into_one_glb(tmp_path: Path) -> None:
    source_a = fixtures.write_stl_binary(tmp_path / "a.stl")
    source_b = fixtures.write_stl_binary(tmp_path / "b.stl")
    output = tmp_path / "scene_game.glb"
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    offset = [[1, 0, 0, 150], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    objects = [
        gameready.SceneObjectSource(
            node_id="node_a",
            name="Crate A",
            path=str(source_a),
            format="stl",
            world_transform=identity,
        ),
        gameready.SceneObjectSource(
            node_id="node_b",
            name="Crate B",
            path=str(source_b),
            format="stl",
            world_transform=offset,
        ),
    ]
    report = gameready.run_scene_in_sandbox(objects, GameRequest(), output, FAST)
    assert report.ok, report.message
    assert report.objects == 2
    assert report.file_bytes == output.stat().st_size > 0
    back = cast(trimesh.Scene, trimesh.load(output))
    for entry in report.per_object:
        assert f"{entry.name}_LOD0" in back.geometry
        assert f"UCX_{entry.name}_00" in back.geometry


@pytest.mark.parametrize(
    ("animation", "clip_name"),
    [
        (
            gameready.SceneAnimationInput(
                kind="revolute",
                node_id="node_b",
                axis="x",
                min_angle_deg=0,
                max_angle_deg=90,
            ),
            "HingedLid",
        ),
        (
            gameready.SceneAnimationInput(
                kind="prismatic",
                node_id="node_b",
                axis="y",
                min_travel_mm=0,
                max_travel_mm=40,
            ),
            "SlidingLid",
        ),
    ],
)
def test_the_sandboxed_scene_export_animates_one_objects_lods_and_collider_together(
    tmp_path: Path,
    animation: gameready.SceneAnimationInput,
    clip_name: str,
) -> None:
    source_a = fixtures.write_stl_binary(tmp_path / f"{animation.kind}-a.stl")
    source_b = fixtures.write_stl_binary(tmp_path / f"{animation.kind}-b.stl")
    output = tmp_path / f"{animation.kind}.glb"
    objects = [
        gameready.SceneObjectSource(
            node_id="node_a",
            name="Base",
            path=str(source_a),
            format="stl",
            world_transform=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        ),
        gameready.SceneObjectSource(
            node_id="node_b",
            name="Moving lid",
            path=str(source_b),
            format="stl",
            world_transform=[[1, 0, 0, 0], [0, 1, 0, 15], [0, 0, 1, 20], [0, 0, 0, 1]],
        ),
    ]
    report = gameready.run_scene_in_sandbox(
        objects,
        GameRequest(lod_ratios=[0.5]),
        output,
        FAST,
        animation=animation,
    )
    assert report.ok, report.message
    assert report.animations == 1
    assert report.animated_node_id == "node_b"
    assert report.animation_kind == animation.kind
    moving = next(entry for entry in report.per_object if entry.node_id == "node_b")
    document = _glb_document(output.read_bytes())
    parent_index = next(
        index for index, node in enumerate(document["nodes"]) if node.get("name") == moving.name
    )
    child_names = {
        document["nodes"][index].get("name")
        for index in document["nodes"][parent_index]["children"]
    }
    assert set(moving.report.lods[index].name for index in range(2)) <= child_names
    assert moving.report.collider is not None and moving.report.collider.name in child_names
    assert document["animations"][0]["name"] == clip_name
    assert {channel["target"]["node"] for channel in document["animations"][0]["channels"]} == {
        parent_index
    }


def test_scene_animation_fails_closed_for_a_pre_rotated_target(tmp_path: Path) -> None:
    source = fixtures.write_stl_binary(tmp_path / "rotated.stl")
    output = tmp_path / "rotated.glb"
    quarter_turn = trimesh.transformations.rotation_matrix(np.pi / 2.0, (0.0, 0.0, 1.0))
    report = gameready.export_scene_file(
        [
            gameready.SceneObjectSource(
                node_id="moving",
                name="Moving lid",
                path=str(source),
                format="stl",
                world_transform=quarter_turn.tolist(),
            )
        ],
        GameRequest(lod_ratios=[]),
        output,
        gameready.SceneAnimationInput(
            kind="revolute",
            node_id="moving",
            axis="x",
            min_angle_deg=0,
            max_angle_deg=90,
        ),
    )
    assert not report.ok
    assert report.message == "game-ready rigid animation needs an axis-aligned mechanism node"
    assert not output.exists()


def test_the_sandboxed_scene_export_refuses_an_invalid_world_transform(tmp_path: Path) -> None:
    source_a = fixtures.write_stl_binary(tmp_path / "a.stl")
    output = tmp_path / "scene_game.glb"
    bad = gameready.SceneObjectSource(
        node_id="node_a",
        name="Crate",
        path=str(source_a),
        format="stl",
        world_transform=[[1, 0, 0], [0, 1, 0]],
    )
    report = gameready.run_scene_in_sandbox([bad], GameRequest(), output, FAST)
    assert not report.ok
    assert report.message


def test_the_sandboxed_scene_export_bounds_the_combined_inputs(tmp_path: Path) -> None:
    source_a = fixtures.write_stl_binary(tmp_path / "a.stl")
    output = tmp_path / "scene_game.glb"
    item = gameready.SceneObjectSource(
        node_id="node_a",
        name="Crate",
        path=str(source_a),
        format="stl",
        world_transform=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    )
    tiny = sandbox.SandboxLimits(max_input_bytes=1, isolate_network=False)
    report = gameready.run_scene_in_sandbox([item], GameRequest(), output, tiny)
    assert not report.ok
    assert report.message and "scene input" in report.message
    assert not output.exists()
