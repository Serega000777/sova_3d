"""F-077: a game-ready GLB — metres, +Y up, base pivot, LODs, UVs, PBR material, a collider."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from tests import fixtures
from worker import gameready, sandbox
from worker.gameready import GameRequest

FAST = sandbox.SandboxLimits(wall_seconds=120, cpu_seconds=120, isolate_network=False)


def _ball() -> trimesh.Trimesh:
    ball = trimesh.creation.icosphere(subdivisions=5, radius=40.0)  # 20480 triangles, mm
    ball.apply_translation((100.0, 100.0, 40.0))  # standing on the bed, far from the origin
    return ball


def test_the_asset_is_metres_y_up_and_stands_on_its_pivot() -> None:
    scene, report = gameready.build(_ball(), GameRequest(name="Ball", max_triangles=5000))
    lod0 = scene.geometry["Ball_LOD0"]
    np.testing.assert_allclose(lod0.bounds, [[-0.04, 0.0, -0.04], [0.04, 0.08, 0.04]], atol=5e-4)
    assert report.size_m == pytest.approx((0.08, 0.08, 0.08), abs=5e-4)
    tall = trimesh.creation.box(extents=(10.0, 20.0, 100.0))  # 100 mm tall on the platform
    tall_scene, _ = gameready.build(tall, GameRequest(pivot="centre", lod_ratios=[]))
    np.testing.assert_allclose(tall_scene.geometry["Model_LOD0"].extents, (0.01, 0.1, 0.02))
    np.testing.assert_allclose(tall_scene.geometry["Model_LOD0"].bounds.mean(axis=0), 0, atol=1e-9)


def test_lods_meet_their_budgets_and_say_how_far_they_stray() -> None:
    scene, report = gameready.build(
        _ball(), GameRequest(name="Ball", max_triangles=5000, lod_ratios=[0.5, 0.2])
    )
    assert [lod.name for lod in report.lods] == ["Ball_LOD0", "Ball_LOD1", "Ball_LOD2"]
    assert [lod.triangles for lod in report.lods] == [5000, 2500, 1000]
    assert report.lods[0].max_deviation_mm == 0
    assert 0 < report.lods[1].max_deviation_mm < report.lods[2].max_deviation_mm < 3.0
    for lod in report.lods:
        shell = scene.geometry[lod.name].copy()
        shell.merge_vertices(merge_tex=True, merge_norm=True)  # UV seams split vertices
        assert shell.is_watertight  # decimation keeps the shell closed


def test_a_small_model_is_not_padded_to_the_budget_nor_crushed_into_a_sheet() -> None:
    cube = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    scene, report = gameready.build(cube, GameRequest(max_triangles=5000))
    assert report.lods[0].triangles == 12 and report.triangles_in == 12
    assert [lod.triangles for lod in report.lods] == [12, 12, 12]  # nothing left to remove
    for lod in report.lods:
        np.testing.assert_allclose(scene.geometry[lod.name].extents, (0.02, 0.02, 0.02))


def test_the_collider_is_convex_and_engine_sized() -> None:
    scene, report = gameready.build(_ball(), GameRequest(name="Ball"))
    assert report.collider is not None and report.collider.name == "UCX_Ball_00"
    collider = scene.geometry["UCX_Ball_00"]
    assert len(collider.faces) <= gameready.MAX_COLLIDER_TRIANGLES
    assert collider.is_convex and collider.is_watertight
    lod0 = scene.geometry["Ball_LOD0"]
    assert collider.volume >= lod0.volume * 0.9  # it wraps the model, it does not shrink it

    _, boxed = gameready.build(_ball(), GameRequest(collider="box"))
    assert boxed.collider is not None and boxed.collider.triangles == 12
    no_scene, none = gameready.build(_ball(), GameRequest(collider="none"))
    assert none.collider is None and not any(n.startswith("UCX_") for n in no_scene.geometry)


def test_uvs_and_a_pbr_material_come_with_every_lod(tmp_path: Path) -> None:
    red = GameRequest(name="Ball", base_color=(1.0, 0.0, 0.0, 1.0), roughness=0.3)
    scene, _ = gameready.build(_ball(), red)
    path = tmp_path / "ball.glb"
    path.write_bytes(scene.export(file_type="glb"))
    back = trimesh.load(path)
    for name in ("Ball_LOD0", "Ball_LOD1", "Ball_LOD2"):
        visual = back.geometry[name].visual
        assert isinstance(visual, trimesh.visual.TextureVisuals)
        assert visual.uv is not None and len(visual.uv) == len(back.geometry[name].vertices)
        assert ((visual.uv >= -1e-6) & (visual.uv <= 1 + 1e-6)).all()  # one packed atlas
        material = visual.material
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
        back.geometry["Crate_LOD0"].extents, (width / 1000, height / 1000, depth / 1000)
    )


def _painted_ball() -> tuple[trimesh.Trimesh, np.ndarray]:
    ball = _ball()
    colours = np.tile(np.array([[30, 60, 220, 255]], dtype=np.uint8), (len(ball.faces), 1))
    colours[ball.triangles_center[:, 2] > 40.0] = (220, 30, 30, 255)  # red cap, blue base
    return ball, colours


def _texel(visual: trimesh.visual.TextureVisuals, uv: np.ndarray) -> np.ndarray:
    image = np.asarray(visual.material.baseColorTexture.convert("RGBA"))
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
    path.write_bytes(scene.export(file_type="glb"))
    back = trimesh.load(path)
    for name in ("Ball_LOD0", "Ball_LOD1", "Ball_LOD2"):
        lod = back.geometry[name]
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


def test_a_painted_glb_keeps_its_colours_through_the_sandboxed_export(tmp_path: Path) -> None:
    ball, colours = _painted_ball()
    painted = ball.copy()
    painted.unmerge_vertices()  # what worker.paint writes: every face its own vertices
    painted.visual = trimesh.visual.ColorVisuals(mesh=painted, face_colors=colours)
    painted.apply_scale(0.001)
    painted.apply_transform(gameready.Z_UP_TO_Y_UP)
    source = tmp_path / "painted.glb"
    source.write_bytes(trimesh.Scene(painted).export(file_type="glb"))
    output = tmp_path / "game.glb"
    report = gameready.run_in_sandbox(source, "glb", GameRequest(name="Ball"), output, FAST)
    assert report.ok, report.message
    assert report.baked_texture_px == 1024
    lod0 = trimesh.load(output).geometry["Ball_LOD0"]
    texels = _texel(lod0.visual, lod0.visual.uv[lod0.faces].mean(axis=1))
    top = lod0.triangles_center[:, 1] > 0.045
    assert (texels[top][:, 0] > 150).mean() > 0.97
