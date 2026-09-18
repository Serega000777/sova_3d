"""T-080..T-082: the adapter interface, the local stub pipeline, and metric scale honesty."""

from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from worker import reconstruction
from worker.importers.common import as_single_mesh
from worker.reconstruction import Frame, ScanInput


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
