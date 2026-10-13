import hashlib

import pytest
import trimesh

from worker.site_plan import build_fence_stl, build_pad_stl, build_path_stl, build_terrain_stl


def _mesh(payload: bytes) -> trimesh.Trimesh:
    return trimesh.load_mesh(trimesh.util.wrap_as_stream(payload), file_type="stl", process=True)


def test_site_meshes_are_deterministic_real_scale_and_closed() -> None:
    terrain = build_terrain_stl(30_000, 20_000, [0, 200, 400, 100])
    assert (
        hashlib.sha256(terrain).digest()
        == hashlib.sha256(build_terrain_stl(30_000, 20_000, [0, 200, 400, 100])).digest()
    )
    terrain_mesh = _mesh(terrain)
    assert terrain_mesh.extents[:2].tolist() == pytest.approx([30_000, 20_000])
    assert terrain_mesh.is_watertight

    pad_mesh = _mesh(build_pad_stl(11_000, 9_000, 450))
    assert pad_mesh.extents.tolist() == pytest.approx([11_000, 9_000, 450])

    path_mesh = _mesh(
        build_path_stl(
            [[-15_000, 0], [-4_000, 0], [0, 2_000]],
            1_200,
            plot_length_mm=30_000,
            plot_width_mm=20_000,
            elevations_mm=[0, 200, 400, 100],
        )
    )
    assert path_mesh.bounds[0][0] == pytest.approx(-15_000)
    assert path_mesh.bounds[1][2] > 60

    fence_mesh = _mesh(
        build_fence_stl(
            30_000,
            20_000,
            ["north", "south"],
            1_500,
            2_500,
            [0, 200, 400, 100],
        )
    )
    assert fence_mesh.bounds[1][2] == pytest.approx(1_900)
    assert fence_mesh.bounds[0][0] == pytest.approx(-15_050)


def test_site_mesh_builders_reject_invalid_geometry() -> None:
    with pytest.raises(ValueError, match="elevation"):
        build_terrain_stl(30_000, 20_000, [0, 20_000, 0, 0])
    with pytest.raises(ValueError, match="segments"):
        build_path_stl(
            [[0, 0], [0, 0]],
            1_000,
            plot_length_mm=30_000,
            plot_width_mm=20_000,
            elevations_mm=[0, 0, 0, 0],
        )
    with pytest.raises(ValueError, match="sides"):
        build_fence_stl(30_000, 20_000, [], 1_500, 2_500, [0, 0, 0, 0])
