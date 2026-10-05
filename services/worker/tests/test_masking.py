"""Foreground-mask orchestration without downloading the live U2-Net weights."""

import json
from pathlib import Path

import pytest

from worker import masking
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
            },
        )

    monkeypatch.setattr(masking.sandbox, "run", fake_run)
    result = masking.mask_frames(frames, tmp_path / "masked")
    assert result.frames[0].path.name == "masked_00001.png"
    assert result.frames[1] is frames[1]
    assert result.frames[2].path.name == "masked_00003.png"
    assert result.frames[0].pose == frames[0].pose
    assert result.report == {
        "mask_applied": True,
        "model": "u2net",
        "frames_masked": 2,
        "foreground_fraction_min": 0.2,
        "foreground_fraction_max": 0.7,
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
        masking.sandbox,
        "run",
        lambda *_args, **_kwargs: SandboxResult(True, output={"ok": True, "outputs": []}),
    )
    with pytest.raises(masking.MaskingError, match="incomplete") as incomplete:
        masking.mask_frames((Frame(0, photo),), tmp_path / "bad")
    assert incomplete.value.code == "masking_bad_output"
