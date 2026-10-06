"""Sandbox child that runs the headless COLMAP exterior pipeline."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ALLOWED_SECTIONS = {"front", "right", "back", "left", "roof"}


def _answer(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, separators=(",", ":")))
    return 0


def _failure(code: str, message: str, **details: Any) -> int:
    return _answer({"ok": False, "code": code, "message": message, "details": details})


def _run(stage: str, command: list[str]) -> tuple[bool, str]:
    try:
        process = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90 * 60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, stage
    text = process.stdout[-32_000:].decode("utf-8", "replace")
    return process.returncode == 0, text


def _gpu_option(help_text: str, modern: str, legacy: str) -> str:
    return modern if modern in help_text else legacy


def _quaternion_rotation(qw: float, qx: float, qy: float, qz: float) -> list[list[float]]:
    return [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ]


def parse_registered_images(
    path: Path, sections_by_name: dict[str, str]
) -> tuple[list[str], dict[str, list[float]]]:
    names: list[str] = []
    directions: dict[str, list[list[float]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 10 or tokens[9] not in sections_by_name:
            continue
        try:
            quaternion = [float(value) for value in tokens[1:5]]
            if not 0.8 <= sum(value * value for value in quaternion) <= 1.2:
                continue
            rotation = _quaternion_rotation(*quaternion)
        except ValueError:
            continue
        # COLMAP stores world-to-camera R; the camera's +Z viewing direction in world
        # coordinates is R^T @ [0, 0, 1], i.e. the third row of R.
        direction = rotation[2]
        name = tokens[9]
        names.append(name)
        directions[sections_by_name[name]].append(direction)

    averaged: dict[str, list[float]] = {}
    for section, values in directions.items():
        mean = [sum(vector[index] for vector in values) / len(values) for index in range(3)]
        norm = math.sqrt(sum(value * value for value in mean))
        if norm > 1e-9:
            averaged[section] = [value / norm for value in mean]
    return names, averaged


def parse_analyzer(text: str) -> tuple[int, float | None]:
    points_match = re.search(r"(?:Points|Points3D)\s*:\s*(\d+)", text, re.IGNORECASE)
    error_match = re.search(r"Mean reprojection error\s*:\s*([0-9.eE+-]+)", text, re.IGNORECASE)
    points = int(points_match.group(1)) if points_match else 0
    error = float(error_match.group(1)) if error_match else None
    return points, error


def main(args: list[str]) -> int:
    if len(args) != 3:
        return _failure("bad_exterior_request", "expected manifest, image path and work path")
    manifest_path = Path(args[0]).resolve()
    image_path = Path(args[1]).resolve()
    work = Path(args[2]).resolve()
    if shutil.which("colmap") is None:
        return _failure("colmap_unavailable", "the worker image does not contain COLMAP")
    try:
        items = json.loads(manifest_path.read_text(encoding="utf-8"))["images"]
        if not isinstance(items, list) or not items:
            raise ValueError("manifest images are invalid")
        sections_by_name: dict[str, str] = {}
        sequences_by_name: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("manifest image is invalid")
            filename = str(item["filename"])
            section = str(item["section"])
            sequence_no = int(item["sequence_no"])
            if (
                Path(filename).name != filename
                or section not in ALLOWED_SECTIONS
                or sequence_no < 0
                or filename in sections_by_name
            ):
                raise ValueError("manifest image is invalid")
            sections_by_name[filename] = section
            sequences_by_name[filename] = sequence_no
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _failure("bad_exterior_manifest", type(exc).__name__)

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    work.mkdir(parents=True, exist_ok=True)
    database = work / "database.db"
    sparse = work / "sparse"
    sparse.mkdir()
    help_process = subprocess.run(
        ["colmap", "feature_extractor", "--help"], capture_output=True, check=False
    )
    feature_help = (help_process.stdout + help_process.stderr).decode("utf-8", "replace")
    feature_gpu = _gpu_option(
        feature_help, "--FeatureExtraction.use_gpu", "--SiftExtraction.use_gpu"
    )
    ok, _ = _run(
        "feature_extraction",
        [
            "colmap",
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(image_path),
            "--ImageReader.single_camera",
            "1",
            "--ImageReader.camera_model",
            "SIMPLE_RADIAL",
            feature_gpu,
            "0",
        ],
    )
    if not ok:
        return _failure("feature_extraction_failed", "COLMAP could not extract image features")

    match_help_process = subprocess.run(
        ["colmap", "exhaustive_matcher", "--help"], capture_output=True, check=False
    )
    match_help = (match_help_process.stdout + match_help_process.stderr).decode("utf-8", "replace")
    match_gpu = _gpu_option(match_help, "--FeatureMatching.use_gpu", "--SiftMatching.use_gpu")
    ok, _ = _run(
        "feature_matching",
        ["colmap", "exhaustive_matcher", "--database_path", str(database), match_gpu, "0"],
    )
    if not ok:
        return _failure("feature_matching_failed", "COLMAP could not match facade features")

    ok, _ = _run(
        "mapping",
        [
            "colmap",
            "mapper",
            "--database_path",
            str(database),
            "--image_path",
            str(image_path),
            "--output_path",
            str(sparse),
        ],
    )
    if not ok:
        return _failure("camera_estimation_failed", "COLMAP could not estimate camera poses")
    models = sorted(path for path in sparse.iterdir() if path.is_dir())
    if not models:
        return _failure("insufficient_overlap", "no connected COLMAP model was reconstructed")
    if len(models) != 1:
        return _failure(
            "disconnected_capture",
            "facade photos formed multiple disconnected COLMAP models",
            components=len(models),
        )
    model = models[0]
    text_model = work / "model_txt"
    text_model.mkdir()
    ok, _ = _run(
        "model_export",
        [
            "colmap",
            "model_converter",
            "--input_path",
            str(model),
            "--output_path",
            str(text_model),
            "--output_type",
            "TXT",
        ],
    )
    if not ok:
        return _failure("model_export_failed", "COLMAP could not export its camera model")
    registered_names, directions = parse_registered_images(
        text_model / "images.txt", sections_by_name
    )
    registered_by_section: dict[str, int] = defaultdict(int)
    registered_sequences_by_section: dict[str, list[int]] = defaultdict(list)
    for name in registered_names:
        section = sections_by_name[name]
        registered_by_section[section] += 1
        registered_sequences_by_section[section].append(sequences_by_name[name])
    missing = [
        section
        for section in ("front", "right", "back", "left")
        if registered_by_section[section] < 3
    ]
    if missing or len(registered_names) < math.ceil(len(items) * 0.7):
        return _failure(
            "disconnected_capture",
            "too few facade photos joined the connected camera solution",
            missing_sections=missing,
            registered_images=len(registered_names),
            total_images=len(items),
            registered_by_section=dict(registered_by_section),
        )

    analyzer_ok, analyzer = _run(
        "model_analysis", ["colmap", "model_analyzer", "--path", str(model)]
    )
    sparse_points, reprojection_error = parse_analyzer(analyzer if analyzer_ok else "")
    mesh_path = work / "exterior_delaunay.ply"
    ok, _ = _run(
        "delaunay_meshing",
        [
            "colmap",
            "delaunay_mesher",
            "--input_path",
            str(model),
            "--input_type",
            "sparse",
            "--output_path",
            str(mesh_path),
        ],
    )
    if not ok or not mesh_path.is_file():
        return _failure("meshing_failed", "COLMAP could not create the exterior surface")
    return _answer(
        {
            "ok": True,
            "mesh_path": str(mesh_path),
            "registered_images": len(registered_names),
            "registered_by_section": dict(registered_by_section),
            "registered_sequences_by_section": {
                section: sorted(sequence_nos)
                for section, sequence_nos in registered_sequences_by_section.items()
            },
            "section_view_directions": directions,
            "sparse_points": sparse_points,
            "mean_reprojection_error_px": reprojection_error,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
