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


def apply_corrections(mask: Any, strokes: Any, sequence_no: int) -> None:
    """Apply bounded normalized add/remove brush strokes to a PIL luminance mask."""
    from PIL import ImageDraw

    if not isinstance(strokes, list) or len(strokes) > 64:
        raise ValueError(f"frame {sequence_no} has invalid correction strokes")
    draw = ImageDraw.Draw(mask)
    for stroke in strokes:
        if not isinstance(stroke, dict) or stroke.get("mode") not in {"add", "remove"}:
            raise ValueError(f"frame {sequence_no} has an invalid correction mode")
        radius = stroke.get("radius")
        points = stroke.get("points")
        if (
            not isinstance(radius, (int, float))
            or not 0.002 <= float(radius) <= 0.25
            or not isinstance(points, list)
            or not 1 <= len(points) <= 512
        ):
            raise ValueError(f"frame {sequence_no} has an invalid correction stroke")
        scaled: list[tuple[int, int]] = []
        for point in points:
            if not isinstance(point, dict):
                raise ValueError(f"frame {sequence_no} has an invalid correction point")
            x = point.get("x")
            y = point.get("y")
            if (
                not isinstance(x, (int, float))
                or not isinstance(y, (int, float))
                or not 0 <= float(x) <= 1
                or not 0 <= float(y) <= 1
            ):
                raise ValueError(f"frame {sequence_no} has an invalid correction point")
            scaled.append(
                (
                    round(float(x) * max(mask.width - 1, 0)),
                    round(float(y) * max(mask.height - 1, 0)),
                )
            )
        fill = 255 if stroke["mode"] == "add" else 0
        diameter = max(1, round(float(radius) * min(mask.size) * 2))
        if len(scaled) > 1:
            draw.line(scaled, fill=fill, width=diameter, joint="curve")
        endpoint_radius = diameter / 2
        for x, y in (scaled[0], scaled[-1]):
            draw.ellipse(
                (
                    round(x - endpoint_radius),
                    round(y - endpoint_radius),
                    round(x + endpoint_radius),
                    round(y + endpoint_radius),
                ),
                fill=fill,
            )


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
            strokes = item.get("correction_strokes", [])
            apply_corrections(mask, strokes, sequence_no)
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
