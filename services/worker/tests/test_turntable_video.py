"""A real bundled ffmpeg encodes the deterministic 3D turntable render."""

from __future__ import annotations

import hashlib
from pathlib import Path

import trimesh

from worker import video
from worker.sandbox import SandboxLimits
from worker.turntable_video import (
    DURATION_SECONDS,
    FPS,
    FRAME_COUNT,
    HEIGHT,
    WIDTH,
    render_turntable_mp4,
)

TEST_LIMITS = SandboxLimits(wall_seconds=45, cpu_seconds=45, isolate_network=False)


def test_turntable_mp4_is_deterministic_and_decodable(tmp_path: Path) -> None:
    source = tmp_path / "asymmetric.stl"
    horizontal = trimesh.creation.box(extents=(30, 12, 8))
    upright = trimesh.creation.box(extents=(8, 8, 24))
    upright.apply_translation((9, 0, 12))
    mesh = trimesh.util.concatenate((horizontal, upright))
    source.write_bytes(mesh.export(file_type="stl"))

    first = render_turntable_mp4(source, "stl", limits=TEST_LIMITS)
    second = render_turntable_mp4(source, "stl", limits=TEST_LIMITS)

    assert first.mp4[4:8] == b"ftyp"
    assert hashlib.sha256(first.mp4).digest() == hashlib.sha256(second.mp4).digest()
    output = tmp_path / "turntable.mp4"
    output.write_bytes(first.mp4)
    probed = video.probe_in_sandbox(output, limits=TEST_LIMITS)
    assert probed.ok, probed
    assert probed.metadata is not None
    assert (probed.metadata.width, probed.metadata.height) == (WIDTH, HEIGHT)
    assert probed.metadata.fps == FPS
    assert probed.metadata.duration_seconds == DURATION_SECONDS
    assert first.frame_count == FRAME_COUNT
    extracted = video.extract_frames_in_sandbox(output, limits=TEST_LIMITS)
    assert extracted.ok, extracted
    assert len({hashlib.sha256(frame.jpeg).digest() for frame in extracted.frames}) > 1


def test_turntable_rejects_empty_geometry(tmp_path: Path) -> None:
    source = tmp_path / "empty.ply"
    source.write_text("ply\nformat ascii 1.0\nelement vertex 0\nelement face 0\nend_header\n")

    try:
        render_turntable_mp4(source, "ply", limits=TEST_LIMITS)
    except ValueError as exc:
        assert "no mesh geometry" in str(exc)
    else:  # pragma: no cover - unrenderable input must fail closed
        raise AssertionError("empty geometry was rendered")
