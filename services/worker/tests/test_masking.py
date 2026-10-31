"""Foreground-mask orchestration without downloading the live U2-Net weights."""

import json
from pathlib import Path

import pytest
from PIL import Image

from worker import masking, masking_child, sandbox
from worker.reconstruction import Frame
from worker.sandbox import SandboxResult


def test_mask_frames_replaces_only_rgb_and_reuses_one_batch_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photo_a = tmp_path / "a.png"
    photo_b = tmp_path / "b.png"
    depth = tmp_path / "depth.bin"
    for path in (photo_a, photo_b, depth):
        path.write_bytes(b"small")
    frames = (
        Frame(1, photo_a, "rgb", {"azimuth_deg": 0}, {"sharpness": 0.8}),
        Frame(2, depth, "depth"),
        Frame(3, photo_b, "rgb"),
    )

    def fake_run(_module: str, args: list[str], **_kwargs: object) -> SandboxResult:
        manifest = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        assert manifest["delight"] is False
        assert [item["sequence_no"] for item in manifest["frames"]] == [1, 3]
        out = Path(args[1])
        outputs = []
        for sequence_no in (1, 3):
            path = out / f"masked_{sequence_no:05d}.png"
            path.write_bytes(b"masked")
            outputs.append({"sequence_no": sequence_no, "path": str(path)})
        return SandboxResult(
            True,
            output={
                "ok": True,
                "outputs": outputs,
                "foreground_fraction_min": 0.2,
                "foreground_fraction_max": 0.7,
                "delight_applied": False,
                "delight_algorithm": None,
                "delight_frames": 0,
                "delight_luminance_cv_before_mean": None,
                "delight_luminance_cv_after_mean": None,
            },
        )

    monkeypatch.setattr(sandbox, "run", fake_run)
    corrections = [
        {
            "sequence_no": 1,
            "strokes": [{"mode": "remove", "radius": 0.1, "points": [{"x": 0.5, "y": 0.5}]}],
        }
    ]
    result = masking.mask_frames(frames, tmp_path / "masked", corrections=corrections)
    assert result.frames[0].path.name == "masked_00001.png"
    assert result.frames[1] is frames[1]
    assert result.frames[2].path.name == "masked_00003.png"
    assert result.frames[0].pose == frames[0].pose
    assert result.report == {
        "mask_applied": True,
        "model": "u2net",
        "frames_masked": 2,
        "frames_corrected": 1,
        "correction_strokes": 1,
        "foreground_fraction_min": 0.2,
        "foreground_fraction_max": 0.7,
        "delight_applied": False,
        "delight_algorithm": None,
        "delight_frames": 0,
        "delight_luminance_cv_before_mean": None,
        "delight_luminance_cv_after_mean": None,
    }


def test_mask_frames_fails_closed_for_no_rgb_or_incomplete_child_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    depth = tmp_path / "depth.bin"
    depth.write_bytes(b"depth")
    with pytest.raises(masking.MaskingError, match="at least one RGB") as no_rgb:
        masking.mask_frames((Frame(0, depth, "depth"),), tmp_path / "none")
    assert no_rgb.value.code == "mask_no_rgb_frames"

    photo = tmp_path / "photo.png"
    photo.write_bytes(b"photo")
    monkeypatch.setattr(
        sandbox,
        "run",
        lambda *_args, **_kwargs: SandboxResult(True, output={"ok": True, "outputs": []}),
    )
    with pytest.raises(masking.MaskingError, match="incomplete") as incomplete:
        masking.mask_frames((Frame(0, photo),), tmp_path / "bad")
    assert incomplete.value.code == "masking_bad_output"


def test_manual_brush_adds_and_removes_pixels_with_normalized_coordinates() -> None:
    mask = Image.new("L", (100, 80), 0)
    masking_child.apply_corrections(
        mask,
        [{"mode": "add", "radius": 0.05, "points": [{"x": 0.5, "y": 0.5}]}],
        4,
    )
    assert mask.getpixel((50, 40)) == 255
    assert mask.getpixel((0, 0)) == 0

    masking_child.apply_corrections(
        mask,
        [
            {
                "mode": "remove",
                "radius": 0.02,
                "points": [{"x": 0.25, "y": 0.5}, {"x": 0.75, "y": 0.5}],
            }
        ],
        4,
    )
    assert mask.getpixel((50, 40)) == 0


def test_manual_brush_rejects_out_of_range_points() -> None:
    mask = Image.new("L", (10, 10), 0)
    with pytest.raises(ValueError, match="invalid correction point"):
        masking_child.apply_corrections(
            mask,
            [{"mode": "add", "radius": 0.1, "points": [{"x": 1.1, "y": 0.5}]}],
            1,
        )


def test_de_light_reduces_broad_luminance_gradient_without_changing_hue() -> None:
    image = Image.new("RGB", (120, 80))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            gain = 0.45 + 0.55 * x / (image.width - 1)
            pixels[x, y] = (round(180 * gain), round(90 * gain), round(45 * gain))
    mask = Image.new("L", image.size, 255)

    normalized, report = masking_child.normalize_foreground_illumination(image, mask)

    assert report["luminance_cv_after"] < report["luminance_cv_before"] * 0.45
    left = normalized.getpixel((10, 40))
    right = normalized.getpixel((109, 40))
    assert abs(left[0] / left[1] - 2.0) < 0.08
    assert abs(right[0] / right[1] - 2.0) < 0.08


def test_mask_frames_rejects_inconsistent_de_light_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"photo")

    def fake_run(_module: str, args: list[str], **_kwargs: object) -> SandboxResult:
        out = Path(args[1])
        path = out / "masked_00000.png"
        path.write_bytes(b"masked")
        return SandboxResult(
            True,
            output={
                "ok": True,
                "outputs": [{"sequence_no": 0, "path": str(path)}],
                "delight_applied": False,
                "delight_algorithm": None,
                "delight_frames": 0,
                "delight_luminance_cv_before_mean": None,
                "delight_luminance_cv_after_mean": None,
            },
        )

    monkeypatch.setattr(sandbox, "run", fake_run)
    with pytest.raises(masking.MaskingError, match="de-light evidence"):
        masking.mask_frames((Frame(0, photo),), tmp_path / "masked", delight=True)
