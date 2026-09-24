"""T-080..T-082: the adapter interface, the local stub pipeline, and metric scale honesty."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from worker import reconstruction
from worker.importers.common import as_single_mesh
from worker.reconstruction import Frame, ReconstructionError, ScanInput, reconstructor_for


def frames(count: int, *, kind: str = "rgb", **quality: float) -> tuple[Frame, ...]:
    return tuple(
        Frame(sequence_no=i, path=Path(f"frame_{i:03d}.jpg"), kind=kind, quality=dict(quality))
        for i in range(count)
    )


def test_providers_are_swappable_and_unknown_ones_fail_loudly() -> None:
    assert "stub" in reconstruction.PROVIDERS
    assert reconstruction.reconstructor_for("stub").name == "stub"
    with pytest.raises(reconstruction.ReconstructionError) as caught:
        reconstruction.reconstructor_for("nope")
    assert caught.value.code == "unknown_provider"


def test_stub_is_deterministic_and_produces_a_solid(tmp_path: Path) -> None:
    scan = ScanInput(frames=frames(20), scale_hint_mm=80.0, scale_confidence=0.8)
    first = reconstruction.reconstructor_for("stub").reconstruct(scan, tmp_path / "a")
    second = reconstruction.reconstructor_for("stub").reconstruct(scan, tmp_path / "b")
    assert first.mesh_path.read_bytes() == second.mesh_path.read_bytes()

    mesh = as_single_mesh(trimesh.load(first.mesh_path, force="mesh"))
    assert mesh is not None
    assert mesh.is_watertight and mesh.volume > 0
    assert max(mesh.extents) == pytest.approx(80.0, rel=1e-3)  # honours the size the user gave
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6)  # sits on the bed like every model
    assert not reconstruction.is_degenerate(first.mesh_path)


def test_a_scan_with_no_frames_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(reconstruction.ReconstructionError) as caught:
        reconstruction.reconstructor_for("stub").reconstruct(ScanInput(frames=()), tmp_path)
    assert caught.value.code == "no_frames"


# --- T-082 scale is a claim, with a source and a confidence ----------------------------------


def test_depth_capture_is_trusted_most(tmp_path: Path) -> None:
    scan = ScanInput(frames=frames(16, kind="depth"), mode="rgb_depth", scale_hint_mm=60.0)
    result = reconstruction.reconstructor_for("stub").reconstruct(scan, tmp_path)
    assert result.scale.source == "depth"
    assert result.scale.confidence >= 0.9
    assert result.scale.warning is None


def test_a_rough_user_estimate_is_flagged(tmp_path: Path) -> None:
    scan = ScanInput(frames=frames(16), scale_hint_mm=60.0, scale_confidence=0.3)
    result = reconstruction.reconstructor_for("stub").reconstruct(scan, tmp_path)
    assert result.scale.source == "scale_hint"
    assert result.scale.warning is not None


def test_without_depth_or_a_hint_the_scale_is_openly_assumed(tmp_path: Path) -> None:
    result = reconstruction.reconstructor_for("stub").reconstruct(
        ScanInput(frames=frames(16)), tmp_path
    )
    assert result.scale.source == "assumed"
    assert result.scale.confidence <= 0.2
    assert "Measure the object" in (result.scale.warning or "")


# --- T-075 capture quality feeds the report ---------------------------------------------------


def test_coverage_uses_poses_when_the_device_has_them() -> None:
    all_round = tuple(
        Frame(sequence_no=i, path=Path("f.jpg"), pose={"azimuth_deg": i * 30}) for i in range(12)
    )
    one_side = tuple(
        Frame(sequence_no=i, path=Path("f.jpg"), pose={"azimuth_deg": i * 3}) for i in range(12)
    )
    assert reconstruction.angular_coverage(ScanInput(frames=all_round)) == pytest.approx(1.0)
    assert reconstruction.angular_coverage(ScanInput(frames=one_side)) < 0.3
    # No poses (plain Expo Go capture): frame count is the only honest signal.
    assert reconstruction.angular_coverage(ScanInput(frames=frames(24))) == pytest.approx(0.5)


def test_frame_quality_counts_the_blurry_ones() -> None:
    mixed = [
        *frames(6, sharpness=0.9),
        *(
            Frame(sequence_no=100 + i, path=Path("b.jpg"), quality={"sharpness": 0.1})
            for i in range(2)
        ),
    ]
    summary = reconstruction.frame_quality(mixed)
    assert summary["frames"] == 8
    assert summary["blurry_frames"] == 2
    assert summary["mean_sharpness"] == pytest.approx(0.7, abs=0.01)


# --- dedicated scanners (F-082): fragments in, one metric model out --------------------------


def _fragment(tmp_path: Path, name: str, geometry: trimesh.Trimesh, **pose: object) -> Frame:
    path = tmp_path / name
    geometry.export(path)
    return Frame(len(list(tmp_path.iterdir())), path, "mesh", dict(pose))


def test_closed_fragments_are_joined_as_one_solid_and_specks_dropped(tmp_path: Path) -> None:
    left = trimesh.creation.box(extents=(44, 40, 20))
    left.apply_translation((22, 20, 10))
    right = trimesh.creation.box(extents=(44, 40, 20))
    right.apply_translation((58, 20, 10))  # overlaps the left one by 8 mm, as scans do
    speck = trimesh.creation.icosphere(subdivisions=1, radius=0.5)
    speck.apply_translation((200, 200, 200))
    frames = (
        _fragment(tmp_path, "left.stl", left, matrix=np.eye(4).tolist()),
        _fragment(tmp_path, "right.stl", right, matrix=np.eye(4).tolist()),
        _fragment(tmp_path, "speck.stl", speck),
    )
    result = reconstructor_for("fusion").reconstruct(
        ScanInput(frames=frames, mode="scanner"), tmp_path / "out"
    )
    mesh = trimesh.load(result.mesh_path, force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight and mesh.volume == pytest.approx(80 * 40 * 20)
    assert result.details["fusion"] == "union" and result.details["noise_pieces_dropped"] == 1
    # the scale is the device's measurement, not a guess
    assert result.scale.source == "device" and result.scale.confidence >= 0.95
    assert result.scale.applied_mm == pytest.approx(80.0)
    assert result.coverage == 1.0  # no turntable angles: nothing to be uncertain about


def test_turntable_poses_place_the_fragments_and_measure_coverage(tmp_path: Path) -> None:
    # the same quarter shell scanned at four angles becomes a whole ring
    quarter = trimesh.creation.cylinder(radius=20, height=10, sections=64)
    quarter.apply_translation((0, 0, 5))
    frames = tuple(_fragment(tmp_path, f"q{i}.stl", quarter, azimuth_deg=i * 90) for i in range(4))
    result = reconstructor_for("fusion").reconstruct(
        ScanInput(frames=frames, mode="scanner"), tmp_path / "out"
    )
    assert 0 < result.coverage < 1  # four angles of twelve sectors
    mesh = trimesh.load(result.mesh_path, force="mesh")
    assert isinstance(mesh, trimesh.Trimesh) and mesh.volume == pytest.approx(
        math.pi * 20**2 * 10, rel=0.02
    )


def test_a_point_cloud_is_meshed_on_a_voxel_grid(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=(60, 30, 20))
    points, _ = trimesh.sample.sample_surface_even(box, 8000, seed=0)
    path = tmp_path / "cloud.ply"
    trimesh.PointCloud(np.asarray(points)).export(path)  # type: ignore[no-untyped-call]
    result = reconstructor_for("fusion").reconstruct(
        ScanInput(frames=(Frame(0, path, "pointcloud", {}),), mode="scanner"), tmp_path / "out"
    )
    mesh = trimesh.load(result.mesh_path, force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight and mesh.volume == pytest.approx(60 * 30 * 20, rel=0.05)
    assert result.details["pointcloud_fragments"] == 1 and "voxel" in result.details["note"]


def test_the_scanner_wins_over_a_wrong_size_hint_and_says_so(tmp_path: Path) -> None:
    frames = (_fragment(tmp_path, "b.stl", trimesh.creation.box(extents=(50, 20, 10))),)
    result = reconstructor_for("fusion").reconstruct(
        ScanInput(frames=frames, mode="scanner", scale_hint_mm=80.0), tmp_path / "out"
    )
    assert result.scale.applied_mm == pytest.approx(50.0)
    assert result.scale.warning and "80" in result.scale.warning


def test_a_scanner_session_without_fragments_is_refused(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(ReconstructionError) as caught:
        reconstructor_for("fusion").reconstruct(
            ScanInput(frames=(Frame(0, photo, "rgb", {}),), mode="scanner"), tmp_path / "out"
        )
    assert caught.value.code == "no_fragments"
