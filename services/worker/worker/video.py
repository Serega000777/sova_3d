"""Sandboxed MP4 probing and representative-frame extraction for AI chat."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from worker import sandbox
from worker.sandbox import DEFAULT_LIMITS, FailureKind, SandboxLimits

MAX_DURATION_SECONDS = 60.0
MAX_LONG_EDGE = 1920
MAX_SHORT_EDGE = 1080
MAX_PIXELS = 1920 * 1080
FRAME_COUNT = 4
MAX_JPEG_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    jpeg: bytes
    timestamp_seconds: float


@dataclass(frozen=True, slots=True)
class VideoResult:
    ok: bool
    metadata: VideoMetadata | None = None
    frames: tuple[ExtractedFrame, ...] = ()
    failure: FailureKind | None = None
    message: str = ""


def _sandbox_failure(result: sandbox.SandboxResult) -> VideoResult:
    detail = result.message
    if result.stderr_tail:
        detail = f"{detail}: {result.stderr_tail}"
    return VideoResult(False, failure=result.failure or FailureKind.crashed, message=detail)


def probe_in_sandbox(input_path: Path, *, limits: SandboxLimits = DEFAULT_LIMITS) -> VideoResult:
    """Read container metadata in a bounded child, without decoding the video stream."""
    result = sandbox.run(
        "worker.video_child",
        ["probe", str(input_path)],
        input_path=input_path,
        limits=limits,
    )
    if not result.ok:
        return _sandbox_failure(result)
    payload = result.output or {}
    if not payload.get("ok"):
        return VideoResult(
            False,
            failure=FailureKind.bad_output,
            message=str(payload.get("message") or "video probe failed"),
        )
    try:
        metadata = VideoMetadata(
            duration_seconds=float(payload["duration_seconds"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            fps=float(payload["fps"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return VideoResult(False, failure=FailureKind.bad_output, message=f"invalid probe: {exc}")

    long_edge = max(metadata.width, metadata.height)
    short_edge = min(metadata.width, metadata.height)
    if metadata.duration_seconds <= 0:
        return VideoResult(False, failure=FailureKind.bad_output, message="video duration is zero")
    if metadata.duration_seconds > MAX_DURATION_SECONDS:
        return VideoResult(
            False,
            metadata=metadata,
            failure=FailureKind.input_too_large,
            message=(
                f"video duration is {metadata.duration_seconds:.2f}s; "
                f"limit is {MAX_DURATION_SECONDS:.0f}s"
            ),
        )
    if (
        long_edge > MAX_LONG_EDGE
        or short_edge > MAX_SHORT_EDGE
        or metadata.width * metadata.height > MAX_PIXELS
    ):
        return VideoResult(
            False,
            metadata=metadata,
            failure=FailureKind.input_too_large,
            message=(f"video resolution is {metadata.width}x{metadata.height}; limit is 1920x1080"),
        )
    return VideoResult(True, metadata=metadata)


def extract_frames_in_sandbox(
    input_path: Path,
    *,
    frame_count: int = FRAME_COUNT,
    limits: SandboxLimits = DEFAULT_LIMITS,
) -> VideoResult:
    """Probe, enforce limits, then decode evenly spaced JPEGs in a second sandbox child."""
    if not 1 <= frame_count <= FRAME_COUNT:
        return VideoResult(
            False,
            failure=FailureKind.bad_output,
            message=f"frame_count must be between 1 and {FRAME_COUNT}",
        )
    probed = probe_in_sandbox(input_path, limits=limits)
    if not probed.ok or probed.metadata is None:
        return probed

    timestamps = [
        probed.metadata.duration_seconds * (index + 0.5) / frame_count
        for index in range(frame_count)
    ]
    with tempfile.TemporaryDirectory(prefix="video-frames-") as temp_dir:
        output_dir = Path(temp_dir)
        result = sandbox.run(
            "worker.video_child",
            [
                "extract",
                str(input_path),
                str(output_dir),
                *(f"{timestamp:.6f}" for timestamp in timestamps),
            ],
            input_path=input_path,
            limits=limits,
        )
        if not result.ok:
            return _sandbox_failure(result)
        payload = result.output or {}
        if not payload.get("ok"):
            return VideoResult(
                False,
                metadata=probed.metadata,
                failure=FailureKind.bad_output,
                message=str(payload.get("message") or "frame extraction failed"),
            )
        names = payload.get("frames")
        if not isinstance(names, list) or len(names) != frame_count:
            return VideoResult(
                False,
                metadata=probed.metadata,
                failure=FailureKind.bad_output,
                message="frame extractor returned an unexpected number of frames",
            )

        frames: list[ExtractedFrame] = []
        for index, name in enumerate(names):
            if not isinstance(name, str) or Path(name).name != name:
                return VideoResult(
                    False,
                    metadata=probed.metadata,
                    failure=FailureKind.bad_output,
                    message="frame extractor returned an unsafe path",
                )
            path = output_dir / name
            try:
                jpeg = path.read_bytes()
            except OSError as exc:
                return VideoResult(
                    False,
                    metadata=probed.metadata,
                    failure=FailureKind.bad_output,
                    message=f"cannot read extracted frame: {exc}",
                )
            if not jpeg.startswith(b"\xff\xd8\xff"):
                return VideoResult(
                    False,
                    metadata=probed.metadata,
                    failure=FailureKind.bad_output,
                    message=f"frame {index + 1} is not JPEG",
                )
            if len(jpeg) > MAX_JPEG_BYTES:
                return VideoResult(
                    False,
                    metadata=probed.metadata,
                    failure=FailureKind.input_too_large,
                    message=f"frame {index + 1} exceeds the 5 MB photo limit",
                )
            frames.append(ExtractedFrame(jpeg=jpeg, timestamp_seconds=timestamps[index]))
    return VideoResult(True, metadata=probed.metadata, frames=tuple(frames))
