"""Deterministic, sandboxed turntable MP4 rendering for immutable 3D versions."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from worker import sandbox
from worker.exporters import _load_platform_mesh
from worker.thumbnail import HEIGHT, WIDTH, render_mesh_png, turntable_camera_axes

FPS = 12
FRAME_COUNT = 12
DURATION_SECONDS = FRAME_COUNT / FPS


@dataclass(frozen=True, slots=True)
class TurntableVideo:
    mp4: bytes
    width: int = WIDTH
    height: int = HEIGHT
    fps: int = FPS
    frame_count: int = FRAME_COUNT
    duration_seconds: float = DURATION_SECONDS


def render_turntable_mp4(
    source_path: Path,
    source_format: str,
    *,
    limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS,
) -> TurntableVideo:
    """Render an untrusted model in one bounded child and return its generated MP4."""
    with tempfile.TemporaryDirectory(prefix="turntable-video-") as tmp:
        output_path = Path(tmp) / "turntable.mp4"
        outcome = sandbox.run(
            "worker.turntable_video",
            [source_format, str(source_path), str(output_path)],
            input_path=source_path,
            limits=limits,
            cwd=output_path.parent,
        )
        if not outcome.ok:
            failure = outcome.failure.value if outcome.failure is not None else "failed"
            detail = f": {outcome.stderr_tail}" if outcome.stderr_tail else ""
            raise ValueError(f"turntable sandbox {failure}: {outcome.message}{detail}")
        payload = outcome.output or {}
        if not payload.get("ok") or not output_path.is_file():
            raise ValueError(str(payload.get("message", "turntable renderer produced no video")))
        data = output_path.read_bytes()
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ValueError("turntable renderer produced an invalid MP4 container")
        return TurntableVideo(mp4=data)


def _ffmpeg() -> str:
    from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore[import-untyped]

    return str(get_ffmpeg_exe())


def _encode_frames(frame_dir: Path, output_path: Path) -> None:
    process = subprocess.run(
        [
            _ffmpeg(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-start_number",
            "0",
            "-i",
            str(frame_dir / "frame-%03d.png"),
            "-frames:v",
            str(FRAME_COUNT),
            "-an",
            "-sn",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-movflags",
            "+faststart",
            "-y",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if process.returncode != 0 or not output_path.is_file():
        detail = process.stderr[-2000:].strip()
        raise ValueError(f"ffmpeg could not encode the turntable video: {detail}")


def _child(source_format: str, source_path: Path, output_path: Path) -> dict[str, Any]:
    mesh, _ = _load_platform_mesh(source_path, source_format)
    frame_dir = output_path.parent / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for index in range(FRAME_COUNT):
        azimuth = 360.0 * index / FRAME_COUNT
        screen_x, screen_y = turntable_camera_axes(azimuth)
        frame = render_mesh_png(
            mesh,
            screen_x,
            screen_y,
            metadata=("sova_turntable_frame", str(index)),
        )
        (frame_dir / f"frame-{index:03d}.png").write_bytes(frame)
    _encode_frames(frame_dir, output_path)
    return {
        "ok": True,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "frame_count": FRAME_COUNT,
        "duration_seconds": DURATION_SECONDS,
    }


if __name__ == "__main__":
    import sys

    try:
        result = _child(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(result))
