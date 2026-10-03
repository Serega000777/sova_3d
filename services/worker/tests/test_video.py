"""MP4 probe/extraction uses the real bundled ffmpeg inside the sandbox."""

from __future__ import annotations

import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from worker import video
from worker.sandbox import FailureKind, SandboxLimits

TEST_LIMITS = SandboxLimits(wall_seconds=30, cpu_seconds=30, isolate_network=False)


def make_mp4(
    path: Path,
    *,
    duration: float = 2.0,
    width: int = 320,
    height: int = 240,
    fps: int = 8,
) -> None:
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_extracts_four_evenly_spaced_jpegs(tmp_path: Path) -> None:
    source = tmp_path / "sample.mp4"
    make_mp4(source)

    result = video.extract_frames_in_sandbox(source, limits=TEST_LIMITS)

    assert result.ok, result
    assert result.metadata is not None
    assert result.metadata.width == 320 and result.metadata.height == 240
    assert result.metadata.duration_seconds == 2.0
    assert result.metadata.fps == 8.0
    assert len(result.frames) == video.FRAME_COUNT
    assert [frame.timestamp_seconds for frame in result.frames] == [0.25, 0.75, 1.25, 1.75]
    assert all(frame.jpeg.startswith(b"\xff\xd8\xff") for frame in result.frames)


def test_rejects_video_over_sixty_seconds_before_extraction(tmp_path: Path) -> None:
    source = tmp_path / "long.mp4"
    make_mp4(source, duration=61.0, width=16, height=16, fps=1)

    result = video.probe_in_sandbox(source, limits=TEST_LIMITS)

    assert not result.ok
    assert result.failure is FailureKind.input_too_large
    assert "duration" in result.message and "60s" in result.message


def test_rejects_resolution_over_1080p_before_extraction(tmp_path: Path) -> None:
    source = tmp_path / "large.mp4"
    make_mp4(source, duration=1.0, width=2048, height=1152, fps=1)

    result = video.probe_in_sandbox(source, limits=TEST_LIMITS)

    assert not result.ok
    assert result.failure is FailureKind.input_too_large
    assert "resolution" in result.message and "1920x1080" in result.message
