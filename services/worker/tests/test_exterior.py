"""T-233 exterior multi-view orchestration and COLMAP report parsing."""

import json
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest
import trimesh

import worker.sandbox as sandbox
from worker import exterior, exterior_child
from worker.exterior_child import parse_analyzer, parse_registered_images
from worker.reconstruction import Frame
from worker.sandbox import SandboxResult


def exterior_frames(tmp_path: Path) -> tuple[Frame, ...]:
    frames: list[Frame] = []
    for section_index, section in enumerate(exterior.REQUIRED_SECTIONS):
        for offset in range(3):
            sequence = section_index * 3 + offset
            path = tmp_path / f"{sequence}.png"
            path.write_bytes(b"image")
            frames.append(
                Frame(
                    sequence,
                    path,
                    "rgb",
                    {"exterior_section": section, "azimuth_deg": sequence * 10},
                )
            )
    return tuple(frames)


def test_colmap_exterior_is_aligned_cleaned_and_scaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = exterior_frames(tmp_path)

    def fake_run(_module: str, args: list[str], **_kwargs: object) -> SandboxResult:
        work = Path(args[2])
        work.mkdir(parents=True)
        main = trimesh.creation.box(extents=(4, 2, 3))
        speck = trimesh.creation.icosphere(subdivisions=1, radius=0.01)
        speck.apply_translation((30, 30, 30))
        mesh_path = work / "exterior_delaunay.ply"
        trimesh.util.concatenate([main, speck]).export(mesh_path)  # type: ignore[no-untyped-call]
        return SandboxResult(
            True,
            output={
                "ok": True,
                "mesh_path": str(mesh_path),
                "registered_images": len(frames),
                "registered_by_section": {section: 3 for section in exterior.REQUIRED_SECTIONS},
                "registered_sequences_by_section": {
                    section: [
                        frame.sequence_no
                        for frame in frames
                        if frame.pose["exterior_section"] == section
                    ]
                    for section in exterior.REQUIRED_SECTIONS
                },
                "section_view_directions": {
                    section: direction.tolist()
                    for section, direction in exterior.SECTION_TARGETS.items()
                    if section != "roof"
                },
                "sparse_points": 2450,
                "mean_reprojection_error_px": 0.42,
            },
        )

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = exterior.reconstruct_exterior(
        frames, tmp_path / "out", scale_hint_mm=12_000, scale_confidence=0.85
    )
    mesh = trimesh.load(result.mesh_path, force="mesh", process=False)
    assert isinstance(mesh, trimesh.Trimesh)
    assert float(mesh.extents.max()) == pytest.approx(12_000, rel=1e-5)
    assert float(mesh.bounds[0, 2]) == pytest.approx(0, abs=1e-5)
    assert result.coverage == 1.0
    report = result.details["multi_view"]
    assert report["registered_by_section"] == {section: 3 for section in exterior.REQUIRED_SECTIONS}
    assert report["section_provenance"]["front"] == {
        "captured_sequence_nos": [0, 1, 2],
        "registered_sequence_nos": [0, 1, 2],
    }
    assert report["isolated_components_removed"] == 1
    assert report["section_alignment_error_deg"] == {
        section: 0.0 for section in exterior.REQUIRED_SECTIONS
    }


def test_exterior_fails_when_colmap_did_not_connect_every_facade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = exterior_frames(tmp_path)
    work = tmp_path / "out" / "colmap"
    work.mkdir(parents=True)
    mesh_path = work / "mesh.ply"
    trimesh.creation.box().export(mesh_path)
    monkeypatch.setattr(
        sandbox,
        "run",
        lambda *_args, **_kwargs: SandboxResult(
            True,
            output={
                "ok": True,
                "mesh_path": str(mesh_path),
                "registered_images": 9,
                "registered_by_section": {
                    section: 3 for section in exterior.REQUIRED_SECTIONS if section != "left"
                },
                "registered_sequences_by_section": {
                    section: [
                        frame.sequence_no
                        for frame in frames
                        if frame.pose["exterior_section"] == section
                    ]
                    for section in exterior.REQUIRED_SECTIONS
                    if section != "left"
                },
                "section_view_directions": {
                    section: direction.tolist()
                    for section, direction in exterior.SECTION_TARGETS.items()
                    if section not in {"left", "roof"}
                },
            },
        ),
    )
    with pytest.raises(exterior.ExteriorReconstructionError) as caught:
        exterior.reconstruct_exterior(
            frames, tmp_path / "out", scale_hint_mm=12_000, scale_confidence=0.8
        )
    assert caught.value.code == "disconnected_capture"
    assert caught.value.details == {"missing_sections": ["left"]}


def test_exterior_rejects_an_unknown_frame_section_before_copying(
    tmp_path: Path,
) -> None:
    frames = list(exterior_frames(tmp_path))
    bad_path = tmp_path / "bad.png"
    bad_path.write_bytes(b"image")
    frames.append(Frame(99, bad_path, "rgb", {"exterior_section": "../../escape"}))

    with pytest.raises(exterior.ExteriorReconstructionError) as caught:
        exterior.reconstruct_exterior(
            tuple(frames), tmp_path / "out", scale_hint_mm=12_000, scale_confidence=0.8
        )

    assert caught.value.code == "invalid_exterior_section"
    assert caught.value.details == {"sequence_no": 99, "section": "../../escape"}


def test_exterior_rejects_a_malformed_registration_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = exterior_frames(tmp_path)
    work = tmp_path / "out" / "colmap"
    work.mkdir(parents=True)
    mesh_path = work / "mesh.ply"
    trimesh.creation.box().export(mesh_path)
    monkeypatch.setattr(
        sandbox,
        "run",
        lambda *_args, **_kwargs: SandboxResult(
            True,
            output={
                "ok": True,
                "mesh_path": str(mesh_path),
                "registered_images": len(frames),
                "registered_by_section": {section: 3 for section in exterior.REQUIRED_SECTIONS},
                "registered_sequences_by_section": {
                    "front": [0, 1, 999],
                    "right": [3, 4, 5],
                    "back": [6, 7, 8],
                    "left": [9, 10, 11],
                },
                "section_view_directions": {
                    section: direction.tolist()
                    for section, direction in exterior.SECTION_TARGETS.items()
                    if section != "roof"
                },
            },
        ),
    )

    with pytest.raises(exterior.ExteriorReconstructionError) as caught:
        exterior.reconstruct_exterior(
            frames, tmp_path / "out", scale_hint_mm=12_000, scale_confidence=0.8
        )

    assert caught.value.code == "exterior_bad_output"


def test_colmap_text_and_analyzer_reports_are_parsed(tmp_path: Path) -> None:
    images = tmp_path / "images.txt"
    images.write_text(
        "# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
        "1 1 0 0 0 0 0 0 1 00000_front.png\n"
        "12.0 20.0 -1 13.0 21.0 -1\n",
        encoding="utf-8",
    )
    names, directions = parse_registered_images(images, {"00000_front.png": "front"})
    assert names == ["00000_front.png"]
    assert directions == {"front": [0.0, 0.0, 1.0]}
    assert parse_analyzer("Points: 1234\nMean reprojection error: 0.67px") == (1234, 0.67)


def test_colmap_delaunay_mesher_is_told_the_model_is_sparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    work = tmp_path / "work"
    items = [
        {
            "filename": f"{sequence_no:05d}_{section}.png",
            "section": section,
            "sequence_no": sequence_no,
        }
        for sequence_no, section in enumerate(
            section for section in exterior.REQUIRED_SECTIONS for _index in range(3)
        )
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"images": items}), encoding="utf-8")
    commands: dict[str, list[str]] = {}

    def fake_run(stage: str, command: list[str]) -> tuple[bool, str]:
        commands[stage] = command
        if stage == "mapping":
            (work / "sparse" / "0").mkdir(parents=True)
        elif stage == "model_export":
            text_model = work / "model_txt"
            image_lines = []
            for image_id, item in enumerate(items, start=1):
                image_lines.extend(
                    [
                        f"{image_id} 1 0 0 0 0 0 0 1 {item['filename']}",
                        "0 0 -1",
                    ]
                )
            (text_model / "images.txt").write_text("\n".join(image_lines), encoding="utf-8")
        elif stage == "delaunay_meshing":
            (work / "exterior_delaunay.ply").write_bytes(b"ply")
        return True, "Points: 40\nMean reprojection error: 0.5px"

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/colmap")
    monkeypatch.setattr(exterior_child, "_run", fake_run)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, b"--SiftExtraction.use_gpu", b""),
    )

    assert exterior_child.main([str(manifest), str(images), str(work)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    command = commands["delaunay_meshing"]
    assert command[command.index("--input_type") + 1] == "sparse"
