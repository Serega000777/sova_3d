"""Isolated child entry point for MP4 metadata probing and JPEG extraction."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(
    r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})(?:[^\r\n]*?([\d.]+) fps)?",
    re.IGNORECASE,
)


def _ffmpeg() -> str:
    from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore[import-untyped]

    return str(get_ffmpeg_exe())


def _probe(path: Path) -> dict[str, object]:
    # ffmpeg exits after printing container/stream metadata because no output is supplied.
    process = subprocess.run(
        [_ffmpeg(), "-nostdin", "-hide_banner", "-i", str(path)],
        capture_output=True,
        check=False,
        text=True,
    )
    output = process.stderr
    duration_match = _DURATION.search(output)
    video_match = _VIDEO.search(output)
    if duration_match is None or video_match is None:
        return {"ok": False, "message": "MP4 metadata is missing duration or video dimensions"}
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    fps = float(video_match.group(3) or 0.0)
    return {
        "ok": True,
        "duration_seconds": duration,
        "width": int(video_match.group(1)),
        "height": int(video_match.group(2)),
        "fps": fps,
    }


def _extract(path: Path, output_dir: Path, timestamps: list[float]) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[str] = []
    for index, timestamp in enumerate(timestamps, start=1):
        name = f"frame-{index}.jpg"
        destination = output_dir / name
        process = subprocess.run(
            [
                _ffmpeg(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-an",
                "-sn",
                "-q:v",
                "3",
                "-y",
                str(destination),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if process.returncode != 0 or not destination.is_file():
            detail = process.stderr[-1000:].strip()
            return {"ok": False, "message": f"could not extract frame {index}: {detail}"}
        frames.append(name)
    return {"ok": True, "frames": frames}


def main(args: list[str]) -> int:
    try:
        if len(args) == 2 and args[0] == "probe":
            result = _probe(Path(args[1]))
        elif len(args) >= 4 and args[0] == "extract":
            result = _extract(
                Path(args[1]),
                Path(args[2]),
                [float(value) for value in args[3:]],
            )
        else:
            result = {
                "ok": False,
                "message": "expected probe <video> or extract <video> <dir> <timestamps...>",
            }
    except Exception as exc:
        result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
