"""Foreground masking for reconstruction photos.

The model runs in a bounded child process because image decoders and ONNX inference both
consume untrusted uploads.  We deliberately select U2-Net instead of rembg's changing
default: U2-Net is a general-purpose salient-object model under Apache-2.0 and has a much
smaller operational footprint than the commercially restricted BRIA default weights.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from worker import sandbox
from worker.sandbox import SandboxLimits

if TYPE_CHECKING:
    from worker.reconstruction import Frame

MASK_MODEL = "u2net"
MASK_CACHE_DIR = Path(__file__).resolve().parent.parent / "rembg_model_cache"
MASK_LIMITS = SandboxLimits(
    wall_seconds=15 * 60,
    cpu_seconds=15 * 60 * (os.cpu_count() or 1),
    memory_bytes=6 * 1024 * 1024 * 1024,
    max_input_bytes=256 * 1024 * 1024,
    max_output_bytes=2 * 1024 * 1024,
    # rembg verifies and downloads one fixed model URL on first use. The untrusted image
    # cannot influence that URL; subsequent runs use the persistent model cache.
    isolate_network=False,
    single_threaded=False,
)


class MaskingError(RuntimeError):
    """Masking failed without allowing reconstruction to silently use the background."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class MaskingResult:
    frames: tuple[Frame, ...]
    report: dict[str, Any]


def mask_frames(frames: tuple[Frame, ...], out_dir: Path) -> MaskingResult:
    """Replace RGB frame paths with neutral-background cutouts made by U2-Net."""
    rgb = [frame for frame in frames if frame.kind == "rgb"]
    if not rgb:
        raise MaskingError("mask_no_rgb_frames", "object masking needs at least one RGB photo")

    total_bytes = 0
    for frame in rgb:
        try:
            total_bytes += frame.path.stat().st_size
        except OSError as exc:
            raise MaskingError("mask_input_missing", "a masking input is unavailable") from exc
    if total_bytes > MASK_LIMITS.max_input_bytes:
        raise MaskingError(
            "mask_input_too_large",
            f"masking inputs total {total_bytes} bytes; limit is {MASK_LIMITS.max_input_bytes}",
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {"sequence_no": frame.sequence_no, "path": str(frame.path)} for frame in rgb
                ]
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    outcome = sandbox.run(
        "worker.masking_child",
        [str(manifest), str(out_dir), str(MASK_CACHE_DIR), MASK_MODEL],
        input_path=manifest,
        limits=MASK_LIMITS,
    )
    if not outcome.ok:
        detail = outcome.message
        if outcome.stderr_tail:
            detail = f"{detail}: {outcome.stderr_tail[-500:]}"
        raise MaskingError("masking_failed", detail)
    payload = outcome.output or {}
    if payload.get("ok") is not True:
        raise MaskingError(
            str(payload.get("code", "masking_failed")),
            str(payload.get("message", "foreground segmentation failed")),
        )

    raw_outputs = payload.get("outputs")
    if not isinstance(raw_outputs, list) or len(raw_outputs) != len(rgb):
        raise MaskingError("masking_bad_output", "masking child returned an incomplete frame set")
    output_root = out_dir.resolve()
    by_sequence: dict[int, Path] = {}
    for item in raw_outputs:
        if not isinstance(item, dict) or not isinstance(item.get("sequence_no"), int):
            raise MaskingError("masking_bad_output", "masking child returned malformed metadata")
        path = Path(str(item.get("path", ""))).resolve()
        if path.parent != output_root or not path.is_file():
            raise MaskingError("masking_bad_output", "masking child returned an unsafe path")
        by_sequence[item["sequence_no"]] = path
    if set(by_sequence) != {frame.sequence_no for frame in rgb}:
        raise MaskingError("masking_bad_output", "masking child returned the wrong frame ids")

    replaced = tuple(
        replace(frame, path=by_sequence[frame.sequence_no]) if frame.kind == "rgb" else frame
        for frame in frames
    )
    return MaskingResult(
        frames=replaced,
        report={
            "mask_applied": True,
            "model": MASK_MODEL,
            "frames_masked": len(rgb),
            "foreground_fraction_min": payload.get("foreground_fraction_min"),
            "foreground_fraction_max": payload.get("foreground_fraction_max"),
        },
    )
