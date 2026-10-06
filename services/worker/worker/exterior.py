"""Metric exterior reconstruction backed by COLMAP SfM and Delaunay meshing."""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

import worker.sandbox as sandbox
from worker.importers.common import as_single_mesh
from worker.sandbox import SandboxLimits

if TYPE_CHECKING:
    from worker.reconstruction import Frame

REQUIRED_SECTIONS = ("front", "right", "back", "left")
OPTIONAL_SECTIONS = ("roof",)
ALLOWED_SECTIONS = (*REQUIRED_SECTIONS, *OPTIONAL_SECTIONS)
SECTION_TARGETS = {
    "front": np.asarray([0.0, 1.0, 0.0]),
    "right": np.asarray([-1.0, 0.0, 0.0]),
    "back": np.asarray([0.0, -1.0, 0.0]),
    "left": np.asarray([1.0, 0.0, 0.0]),
    "roof": np.asarray([0.0, 0.0, -1.0]),
}
EXTERIOR_LIMITS = SandboxLimits(
    wall_seconds=2 * 60 * 60,
    cpu_seconds=2 * 60 * 60 * (os.cpu_count() or 1),
    memory_bytes=12 * 1024 * 1024 * 1024,
    max_input_bytes=2 * 1024 * 1024 * 1024,
    max_output_bytes=2 * 1024 * 1024,
    isolate_network=True,
    single_threaded=False,
)


class ExteriorReconstructionError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class ExteriorResult:
    mesh_path: Path
    coverage: float
    details: dict[str, Any]


def _orientation(
    directions: dict[str, list[float]],
) -> tuple[np.ndarray, dict[str, float]]:
    missing = [section for section in REQUIRED_SECTIONS if section not in directions]
    if missing:
        raise ExteriorReconstructionError(
            "disconnected_capture",
            "COLMAP did not register camera views for every facade",
            {"missing_sections": missing},
        )
    sections = [section for section in (*REQUIRED_SECTIONS, "roof") if section in directions]
    try:
        source = np.asarray([directions[section] for section in sections], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ExteriorReconstructionError(
            "invalid_camera_solution", "COLMAP returned invalid camera directions"
        ) from exc
    if source.shape != (len(sections), 3):
        raise ExteriorReconstructionError(
            "invalid_camera_solution", "COLMAP returned invalid camera directions"
        )
    norms = np.linalg.norm(source, axis=1)
    if np.any(~np.isfinite(source)) or np.any(norms <= 1e-9):
        raise ExteriorReconstructionError(
            "invalid_camera_solution", "COLMAP returned invalid camera directions"
        )
    source /= norms[:, None]
    target = np.asarray([SECTION_TARGETS[section] for section in sections], dtype=float)
    rotation, _ = Rotation.align_vectors(target, source)
    matrix = np.eye(4)
    matrix[:3, :3] = rotation.as_matrix()
    aligned = rotation.apply(source)
    errors = {
        section: round(math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0)))), 3)
        for section, a, b in zip(sections, aligned, target, strict=True)
    }
    if max(errors.values()) > 45.0:
        raise ExteriorReconstructionError(
            "section_alignment_failed",
            "estimated cameras disagree with the declared facade order",
            {"angular_error_deg": errors},
        )
    return matrix, errors


def _drop_isolated(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, int]:
    pieces = list(mesh.split(only_watertight=False))
    if len(pieces) <= 1:
        return mesh, 0
    sizes = np.asarray([float(np.linalg.norm(piece.extents)) for piece in pieces], dtype=float)
    largest = float(sizes.max())
    kept = [piece for piece, size in zip(pieces, sizes, strict=True) if size >= largest * 0.02]
    if not kept:
        raise ExteriorReconstructionError("empty_reconstruction", "no exterior surface survived")
    return cast(trimesh.Trimesh, trimesh.util.concatenate(kept)), len(pieces) - len(kept)


def reconstruct_exterior(
    frames: tuple[Frame, ...],
    out_dir: Path,
    *,
    scale_hint_mm: float | None,
    scale_confidence: float | None,
) -> ExteriorResult:
    """Estimate cameras, make one connected surface, align facades, and apply metric scale."""
    if not scale_hint_mm or not math.isfinite(scale_hint_mm) or scale_hint_mm <= 0:
        raise ExteriorReconstructionError(
            "metric_scale_required", "exterior reconstruction needs a measured maximum dimension"
        )
    grouped: dict[str, list[Frame]] = {}
    for frame in frames:
        section = frame.pose.get("exterior_section")
        if frame.kind != "rgb":
            continue
        if not isinstance(section, str) or section not in ALLOWED_SECTIONS:
            raise ExteriorReconstructionError(
                "invalid_exterior_section",
                "every exterior RGB frame must name a supported facade section",
                {"sequence_no": frame.sequence_no, "section": section},
            )
        grouped.setdefault(section, []).append(frame)
    missing = [section for section in REQUIRED_SECTIONS if len(grouped.get(section, [])) < 3]
    if missing:
        raise ExteriorReconstructionError(
            "insufficient_section_frames",
            "each facade needs at least three RGB frames",
            {"missing_sections": missing},
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    images = out_dir / "images"
    images.mkdir()
    manifest_images: list[dict[str, Any]] = []
    total_bytes = 0
    for frame in sorted(frames, key=lambda item: item.sequence_no):
        section = frame.pose.get("exterior_section")
        if frame.kind != "rgb" or not isinstance(section, str):
            continue
        suffix = frame.path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ExteriorReconstructionError(
                "unsupported_exterior_frame", "exterior RGB frames must be JPEG or PNG"
            )
        total_bytes += frame.path.stat().st_size
        name = f"{frame.sequence_no:05d}_{section}{suffix}"
        shutil.copyfile(frame.path, images / name)
        manifest_images.append(
            {"filename": name, "section": section, "sequence_no": frame.sequence_no}
        )
    if total_bytes > EXTERIOR_LIMITS.max_input_bytes:
        raise ExteriorReconstructionError(
            "exterior_input_too_large", "exterior photo set exceeds the 2 GiB worker limit"
        )

    manifest = out_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"images": manifest_images}, separators=(",", ":")), encoding="utf-8"
    )
    outcome = sandbox.run(
        "worker.exterior_child",
        [str(manifest), str(images), str(out_dir / "colmap")],
        input_path=manifest,
        limits=EXTERIOR_LIMITS,
    )
    if not outcome.ok:
        raise ExteriorReconstructionError(
            "exterior_reconstruction_failed", outcome.message or "COLMAP process failed"
        )
    payload = outcome.output or {}
    if payload.get("ok") is not True:
        raise ExteriorReconstructionError(
            str(payload.get("code", "exterior_reconstruction_failed")),
            str(payload.get("message", "COLMAP could not reconstruct the exterior")),
            payload.get("details") if isinstance(payload.get("details"), dict) else None,
        )
    candidate = Path(str(payload.get("mesh_path", ""))).resolve()
    colmap_root = (out_dir / "colmap").resolve()
    if candidate.parent != colmap_root or not candidate.is_file():
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned an unsafe mesh path"
        )
    loaded = as_single_mesh(trimesh.load(candidate, force="mesh", process=False))
    if loaded is None or loaded.is_empty or len(loaded.faces) < 4:
        raise ExteriorReconstructionError(
            "empty_reconstruction", "COLMAP produced no usable exterior surface"
        )
    mesh, removed = _drop_isolated(loaded)
    directions = payload.get("section_view_directions")
    if not isinstance(directions, dict):
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned no section camera directions"
        )
    transform, angular_errors = _orientation(directions)
    mesh.apply_transform(transform)
    native_extent = float(mesh.extents.max())
    if not math.isfinite(native_extent) or native_extent <= 0:
        raise ExteriorReconstructionError(
            "degenerate_mesh", "COLMAP exterior surface has no finite extent"
        )
    scale_factor = scale_hint_mm / native_extent
    mesh.apply_scale(scale_factor)
    mesh.apply_translation((-mesh.centroid[0], -mesh.centroid[1], -mesh.bounds[0, 2]))
    mesh.remove_unreferenced_vertices()
    metric_path = out_dir / "exterior_metric.stl"
    mesh.export(metric_path)

    try:
        registered = int(payload.get("registered_images", -1))
    except (TypeError, ValueError) as exc:
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned an invalid registration count"
        ) from exc
    if registered < 0 or registered > len(manifest_images):
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned an invalid registration count"
        )
    coverage = registered / len(manifest_images)
    section_counts = payload.get("registered_by_section")
    registered_sequences = payload.get("registered_sequences_by_section")
    if not isinstance(section_counts, dict) or not isinstance(registered_sequences, dict):
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned no per-section registration report"
        )
    if set(section_counts) - set(ALLOWED_SECTIONS) or set(registered_sequences) - set(
        ALLOWED_SECTIONS
    ):
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP returned an invalid per-section registration report"
        )
    section_provenance: dict[str, dict[str, list[int]]] = {}
    counted = 0
    for section in ALLOWED_SECTIONS:
        captured = [frame.sequence_no for frame in grouped.get(section, [])]
        count = section_counts.get(section, 0)
        sequence_nos = registered_sequences.get(section, [])
        if (
            type(count) is not int
            or count < 0
            or count > len(captured)
            or not isinstance(sequence_nos, list)
            or any(type(sequence_no) is not int for sequence_no in sequence_nos)
            or len(sequence_nos) != count
            or len(set(sequence_nos)) != len(sequence_nos)
            or not set(sequence_nos).issubset(captured)
        ):
            raise ExteriorReconstructionError(
                "exterior_bad_output",
                "COLMAP returned an invalid per-section registration report",
            )
        counted += count
        if captured:
            section_provenance[section] = {
                "captured_sequence_nos": captured,
                "registered_sequence_nos": sequence_nos,
            }
    if counted != registered:
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP registration totals do not match"
        )
    details = {
        "frames": len(manifest_images),
        "placeholder": False,
        "multi_view": {
            "engine": "colmap",
            "registered_images": registered,
            "registered_fraction": round(coverage, 4),
            "sparse_points": int(payload.get("sparse_points", 0)),
            "mean_reprojection_error_px": payload.get("mean_reprojection_error_px"),
            "registered_by_section": section_counts,
            "section_provenance": section_provenance,
            "section_alignment_error_deg": angular_errors,
            "isolated_components_removed": removed,
            "native_max_extent": round(native_extent, 6),
            "metric_scale_factor": round(scale_factor, 9),
            "scale_confidence": round(float(scale_confidence or 0.6), 3),
        },
        "note": (
            "COLMAP estimated cameras from overlapping facade photos and triangulated a "
            "connected exterior surface. The measured maximum dimension sets metric scale; "
            "the report retains per-section registration and reprojection error."
        ),
    }
    return ExteriorResult(metric_path, coverage, details)
