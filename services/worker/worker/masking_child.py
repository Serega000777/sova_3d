"""Sandbox child for U2-Net foreground segmentation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_PIXELS = 50_000_000
MIN_FOREGROUND_FRACTION = 0.002
MAX_FOREGROUND_FRACTION = 0.998


def _fail(code: str, message: str) -> int:
    print(json.dumps({"ok": False, "code": code, "message": message}))
    return 0


def main(args: list[str]) -> int:
    if len(args) != 4:
        return _fail("masking_bad_request", "expected manifest, output dir, cache dir and model")
    manifest_path = Path(args[0]).resolve()
    output_dir = Path(args[1]).resolve()
    cache_dir = Path(args[2]).resolve()
    model = args[3]
    if model != "u2net":
        return _fail("masking_model_refused", "only the reviewed u2net model is allowed")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = payload["frames"]
        if not isinstance(items, list) or not items:
            raise ValueError("manifest has no frames")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _fail("masking_bad_manifest", str(exc))

    # rembg reads this variable when creating its session. Keep model files in an explicit,
    # persistent deployment volume rather than a service user's home directory.
    os.environ["REMBG_HOME"] = str(cache_dir)
    try:
        from PIL import Image, ImageOps
        from rembg import new_session, remove

        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        session = new_session(model)
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[dict[str, Any]] = []
        fractions: list[float] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("frame entry is not an object")
            sequence_no = item.get("sequence_no")
            if not isinstance(sequence_no, int) or sequence_no < 0:
                raise ValueError("frame sequence number is invalid")
            source = Path(str(item.get("path", ""))).resolve()
            with Image.open(source) as opened:
                opened.load()
                if opened.width * opened.height > MAX_PIXELS:
                    raise ValueError(f"frame {sequence_no} exceeds {MAX_PIXELS} pixels")
                image = ImageOps.exif_transpose(opened).convert("RGB")

            generated = remove(image, session=session, only_mask=True)
            mask = generated.convert("L")
            histogram = mask.histogram()
            pixels = mask.width * mask.height
            foreground = sum(histogram[16:]) / pixels
            if foreground <= MIN_FOREGROUND_FRACTION:
                return _fail(
                    "mask_no_foreground",
                    f"frame {sequence_no} contains no reliable foreground object",
                )
            if foreground >= MAX_FOREGROUND_FRACTION:
                return _fail(
                    "mask_no_background",
                    f"frame {sequence_no} has no separable background",
                )

            # Existing reconstructors consume RGB. Composite onto a neutral background rather
            # than discarding alpha implicitly (which PIL would turn black for Shap-E).
            cutout = Image.composite(image, Image.new("RGB", image.size, "white"), mask)
            destination = output_dir / f"masked_{sequence_no:05d}.png"
            cutout.save(destination, format="PNG", optimize=True)
            fractions.append(foreground)
            outputs.append(
                {
                    "sequence_no": sequence_no,
                    "path": str(destination),
                    "foreground_fraction": round(foreground, 6),
                }
            )
    except Exception as exc:
        # The parent reports a stable error code; do not leak a traceback or local path to the
        # API response. stderr is also bounded by the sandbox runner.
        return _fail(
            "masking_failed", f"{type(exc).__name__}: foreground segmentation did not complete"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "outputs": outputs,
                "foreground_fraction_min": round(min(fractions), 6),
                "foreground_fraction_max": round(max(fractions), 6),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
