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
from PIL import Image
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from trimesh.visual import ColorVisuals
from trimesh.visual.material import PBRMaterial

import worker.sandbox as sandbox
from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh
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
    texture_context_path: Path | None = None


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


def _camera_matrix(qvec: list[float]) -> np.ndarray:
    if len(qvec) != 4 or any(not math.isfinite(value) for value in qvec):
        raise ValueError("invalid camera quaternion")
    qw, qx, qy, qz = qvec
    return cast(np.ndarray, Rotation.from_quat([qx, qy, qz, qw]).as_matrix())


def _project_pixels(
    points: np.ndarray,
    depth: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    radial: float,
) -> tuple[np.ndarray, np.ndarray]:
    safe = np.where(depth > 1e-9, depth, 1.0)
    x = points[..., 0] / safe
    y = points[..., 1] / safe
    distortion = 1.0 + radial * (x * x + y * y)
    return fx * x * distortion + cx, fy * y * distortion + cy


def _photo_face_colours(
    mesh: trimesh.Trimesh, cameras: object, images_dir: Path
) -> tuple[np.ndarray, dict[str, Any]]:
    """Project registered photos onto face centres and fill only unseen seams by proximity."""
    if not isinstance(cameras, list) or not cameras:
        raise ExteriorReconstructionError(
            "texture_projection_failed", "COLMAP returned no registered camera calibration"
        )
    centres = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    if not len(centres) or np.any(~np.isfinite(centres)) or np.any(~np.isfinite(normals)):
        raise ExteriorReconstructionError(
            "texture_projection_failed", "the exterior surface cannot receive photo colour"
        )
    best = np.full(len(centres), -np.inf, dtype=float)
    colours = np.zeros((len(centres), 4), dtype=np.uint8)
    used: set[str] = set()
    seen_names: set[str] = set()
    for item in cameras:
        if not isinstance(item, dict):
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP returned an invalid registered camera"
            )
        try:
            filename = str(item["filename"])
            qvec = [float(value) for value in item["qvec"]]
            tvec = np.asarray(item["tvec"], dtype=float)
            model = str(item["model"])
            width = int(item["width"])
            height = int(item["height"])
            params = [float(value) for value in item["params"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP returned an invalid registered camera"
            ) from exc
        if (
            Path(filename).name != filename
            or filename in seen_names
            or tvec.shape != (3,)
            or np.any(~np.isfinite(tvec))
            or width <= 0
            or height <= 0
            or any(not math.isfinite(value) for value in params)
        ):
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP returned an invalid registered camera"
            )
        seen_names.add(filename)
        if model == "SIMPLE_RADIAL" and len(params) == 4:
            fx = fy = params[0]
            cx, cy, radial = params[1:]
        elif model == "SIMPLE_PINHOLE" and len(params) == 3:
            fx = fy = params[0]
            cx, cy = params[1:]
            radial = 0.0
        elif model == "PINHOLE" and len(params) == 4:
            fx, fy, cx, cy = params
            radial = 0.0
        else:
            raise ExteriorReconstructionError(
                "texture_projection_failed", f"unsupported COLMAP camera model {model}"
            )
        if fx <= 0 or fy <= 0:
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP returned invalid camera intrinsics"
            )
        image_path = (images_dir / filename).resolve()
        if image_path.parent != images_dir.resolve() or not image_path.is_file():
            raise ExteriorReconstructionError(
                "texture_projection_failed", "a registered source photo is missing"
            )
        try:
            with Image.open(image_path) as opened:
                rgb = np.asarray(opened.convert("RGB"))
        except (OSError, ValueError) as exc:
            raise ExteriorReconstructionError(
                "texture_projection_failed", "a registered source photo cannot be decoded"
            ) from exc
        if rgb.shape[:2] != (height, width):
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP camera dimensions do not match the source photo"
            )

        try:
            rotation = _camera_matrix(qvec)
        except ValueError as exc:
            raise ExteriorReconstructionError(
                "exterior_bad_output", "COLMAP returned an invalid camera quaternion"
            ) from exc
        camera_points = centres @ rotation.T + tvec
        z = camera_points[:, 2]
        safe_z = np.where(z > 1e-9, z, 1.0)
        x = camera_points[:, 0] / safe_z
        y = camera_points[:, 1] / safe_z
        radius2 = x * x + y * y
        distortion = 1.0 + radial * radius2
        u = fx * x * distortion + cx
        v = fy * y * distortion + cy
        camera_centre = -(rotation.T @ tvec)
        to_camera = camera_centre - centres
        distances = np.linalg.norm(to_camera, axis=1)
        unit_view = to_camera / np.maximum(distances[:, None], 1e-12)
        facing = np.einsum("ij,ij->i", normals, unit_view)
        valid = (
            (z > 1e-9)
            & (u >= 0)
            & (u < width)
            & (v >= 0)
            & (v < height)
            & (facing > 0.05)
        )
        score = np.where(valid, facing / np.maximum(distances * distances, 1e-12), -np.inf)
        take = score > best
        if not np.any(take):
            continue
        rows = np.clip(np.rint(v[take]).astype(int), 0, height - 1)
        columns = np.clip(np.rint(u[take]).astype(int), 0, width - 1)
        colours[take, :3] = rgb[rows, columns]
        colours[take, 3] = 255
        best[take] = score[take]
        used.add(filename)

    projected = np.isfinite(best)
    projected_count = int(np.count_nonzero(projected))
    if projected_count == 0:
        raise ExteriorReconstructionError(
            "texture_projection_failed", "no exterior face is visible in a registered photo"
        )
    missing = ~projected
    if np.any(missing):
        nearest = cKDTree(centres[projected]).query(centres[missing], k=1)[1]
        colours[missing] = colours[projected][np.asarray(nearest, dtype=np.int64)]
    return colours, {
        "photo_projected_faces": projected_count,
        "photo_projected_fraction": round(projected_count / len(centres), 4),
        "proximity_filled_faces": int(np.count_nonzero(missing)),
        "registered_texture_cameras": len(cameras),
        "texture_cameras_used": len(used),
    }


def export_projected_texture_glb(
    mesh_mm: trimesh.Trimesh, context_path: Path, size: int, output: Path
) -> dict[str, Any]:
    """Embed registered facade photos in one atlas and map repaired faces into it."""
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
        cameras = context["cameras"]
        source_from_platform = np.asarray(context["source_from_platform"], dtype=float)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ExteriorReconstructionError(
            "texture_projection_failed", "the exterior texture context is invalid"
        ) from exc
    if (
        not isinstance(cameras, list)
        or not cameras
        or source_from_platform.shape != (4, 4)
        or np.any(~np.isfinite(source_from_platform))
        or size < 256
    ):
        raise ExteriorReconstructionError(
            "texture_projection_failed", "the exterior texture context is invalid"
        )

    source_mesh = mesh_mm.copy()
    source_mesh.apply_transform(source_from_platform)
    centres = np.asarray(source_mesh.triangles_center, dtype=float)
    normals = np.asarray(source_mesh.face_normals, dtype=float)
    triangles = np.asarray(source_mesh.triangles, dtype=float)
    best = np.full(len(centres), -np.inf, dtype=float)
    assignments = np.full(len(centres), -1, dtype=np.int64)
    corner_pixels = np.zeros((len(centres), 3, 2), dtype=float)
    image_paths: list[Path] = []
    image_sizes: list[tuple[int, int]] = []
    images_dir = context_path.parent / "images"

    for camera_index, item in enumerate(cameras):
        if not isinstance(item, dict):
            raise ExteriorReconstructionError(
                "texture_projection_failed", "the exterior camera data is invalid"
            )
        try:
            filename = str(item["filename"])
            qvec = [float(value) for value in item["qvec"]]
            tvec = np.asarray(item["tvec"], dtype=float)
            model = str(item["model"])
            width = int(item["width"])
            height = int(item["height"])
            params = [float(value) for value in item["params"]]
            rotation = _camera_matrix(qvec)
        except (KeyError, TypeError, ValueError) as exc:
            raise ExteriorReconstructionError(
                "texture_projection_failed", "the exterior camera data is invalid"
            ) from exc
        if model == "SIMPLE_RADIAL" and len(params) == 4:
            fx = fy = params[0]
            cx, cy, radial = params[1:]
        elif model == "SIMPLE_PINHOLE" and len(params) == 3:
            fx = fy = params[0]
            cx, cy = params[1:]
            radial = 0.0
        elif model == "PINHOLE" and len(params) == 4:
            fx, fy, cx, cy = params
            radial = 0.0
        else:
            raise ExteriorReconstructionError(
                "texture_projection_failed", f"unsupported COLMAP camera model {model}"
            )
        path = (images_dir / filename).resolve()
        if (
            Path(filename).name != filename
            or path.parent != images_dir.resolve()
            or not path.is_file()
            or tvec.shape != (3,)
            or width <= 1
            or height <= 1
            or fx <= 0
            or fy <= 0
        ):
            raise ExteriorReconstructionError(
                "texture_projection_failed", "the exterior camera data is invalid"
            )
        try:
            with Image.open(path) as opened:
                image_size = opened.size
        except (OSError, ValueError) as exc:
            raise ExteriorReconstructionError(
                "texture_projection_failed", "a registered source photo cannot be decoded"
            ) from exc
        if image_size != (width, height):
            raise ExteriorReconstructionError(
                "texture_projection_failed", "camera dimensions do not match the source photo"
            )
        image_paths.append(path)
        image_sizes.append((width, height))

        camera_centres = centres @ rotation.T + tvec
        camera_corners = triangles @ rotation.T + tvec
        centre_z = camera_centres[:, 2]
        corner_z = camera_corners[:, :, 2]

        centre_u, centre_v = _project_pixels(
            camera_centres, centre_z, fx, fy, cx, cy, radial
        )
        corner_u, corner_v = _project_pixels(
            camera_corners, corner_z, fx, fy, cx, cy, radial
        )
        camera_centre = -(rotation.T @ tvec)
        to_camera = camera_centre - centres
        distances = np.linalg.norm(to_camera, axis=1)
        facing = np.einsum(
            "ij,ij->i", normals, to_camera / np.maximum(distances[:, None], 1e-12)
        )
        valid = (
            (centre_z > 1e-9)
            & np.all(corner_z > 1e-9, axis=1)
            & (centre_u >= 0)
            & (centre_u < width)
            & (centre_v >= 0)
            & (centre_v < height)
            & np.all((corner_u >= 0) & (corner_u < width), axis=1)
            & np.all((corner_v >= 0) & (corner_v < height), axis=1)
            & (facing > 0.05)
        )
        score = np.where(valid, facing / np.maximum(distances * distances, 1e-12), -np.inf)
        take = score > best
        assignments[take] = camera_index
        corner_pixels[take, :, 0] = corner_u[take]
        corner_pixels[take, :, 1] = corner_v[take]
        best[take] = score[take]

    projected = assignments >= 0
    projected_count = int(np.count_nonzero(projected))
    if projected_count == 0:
        raise ExteriorReconstructionError(
            "texture_projection_failed", "no repaired exterior face fits a registered photo"
        )
    used = sorted(int(index) for index in np.unique(assignments[projected]))
    cells = len(used) + 1
    columns = math.ceil(math.sqrt(cells))
    rows = math.ceil(cells / columns)
    atlas = Image.new("RGB", (size, size), (128, 128, 128))
    cell_bounds: dict[int, tuple[int, int, int, int]] = {}
    for cell_index, camera_index in enumerate(used):
        column = cell_index % columns
        row = cell_index // columns
        x0, x1 = column * size // columns, (column + 1) * size // columns
        y0, y1 = row * size // rows, (row + 1) * size // rows
        try:
            with Image.open(image_paths[camera_index]) as opened:
                tile = opened.convert("RGB").resize(
                    (x1 - x0, y1 - y0), Image.Resampling.LANCZOS
                )
        except (OSError, ValueError) as exc:
            raise ExteriorReconstructionError(
                "texture_projection_failed", "a registered source photo cannot be decoded"
            ) from exc
        atlas.paste(tile, (x0, y0))
        cell_bounds[camera_index] = (x0, y0, x1, y1)
    fallback_cell = len(used)
    fallback_column = fallback_cell % columns
    fallback_row = fallback_cell // columns
    fallback_bounds = (
        fallback_column * size // columns,
        fallback_row * size // rows,
        (fallback_column + 1) * size // columns,
        (fallback_row + 1) * size // rows,
    )

    uv = np.empty((len(centres), 3, 2), dtype=float)
    for camera_index in used:
        selected = assignments == camera_index
        x0, y0, x1, y1 = cell_bounds[camera_index]
        width, height = image_sizes[camera_index]
        uv[selected, :, 0] = (
            x0 + corner_pixels[selected, :, 0] / (width - 1) * (x1 - x0 - 1)
        ) / (size - 1)
        uv[selected, :, 1] = 1.0 - (
            y0 + corner_pixels[selected, :, 1] / (height - 1) * (y1 - y0 - 1)
        ) / (size - 1)
    fallback = ~projected
    fx0, fy0, fx1, fy1 = fallback_bounds
    uv[fallback, :, 0] = ((fx0 + fx1 - 1) / 2) / (size - 1)
    uv[fallback, :, 1] = 1.0 - ((fy0 + fy1 - 1) / 2) / (size - 1)

    vertices = np.asarray(mesh_mm.vertices)[np.asarray(mesh_mm.faces)].reshape((-1, 3))
    faces = np.arange(len(vertices), dtype=np.int64).reshape((-1, 3))
    textured = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    textured.apply_scale(0.001)
    textured.apply_transform(Z_UP_TO_Y_UP)
    material = PBRMaterial(
        name="ExteriorPhotoAtlas",
        baseColorTexture=atlas,
        metallicFactor=0.0,
        roughnessFactor=0.8,
    )
    textured.visual = trimesh.visual.TextureVisuals(
        uv=uv.reshape((-1, 2)), material=material
    )
    payload = trimesh.Scene(textured).export(file_type="glb")
    data = payload if isinstance(payload, bytes) else bytes(payload)
    output.write_bytes(data)
    return {
        "texture_baked": True,
        "texture_size": size,
        "file_bytes": len(data),
        "photo_projected_faces": projected_count,
        "photo_projected_fraction": round(projected_count / len(centres), 4),
        "fallback_faces": int(np.count_nonzero(fallback)),
        "atlas_source_photos": len(used),
    }


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
    cameras = payload.get("registered_cameras")
    camera_count = len(cameras) if isinstance(cameras, list) else -1
    if camera_count != registered:
        raise ExteriorReconstructionError(
            "exterior_bad_output", "COLMAP camera calibration totals do not match"
        )
    photo_colours, texture_projection = _photo_face_colours(mesh, cameras, images)

    mesh.apply_transform(transform)
    native_extent = float(mesh.extents.max())
    if not math.isfinite(native_extent) or native_extent <= 0:
        raise ExteriorReconstructionError(
            "degenerate_mesh", "COLMAP exterior surface has no finite extent"
        )
    scale_factor = scale_hint_mm / native_extent
    mesh.apply_scale(scale_factor)
    translation = np.asarray((-mesh.centroid[0], -mesh.centroid[1], -mesh.bounds[0, 2]))
    mesh.apply_translation(translation)
    mesh.remove_unreferenced_vertices()
    mesh.unmerge_vertices()
    mesh.visual = ColorVisuals(mesh=mesh, face_colors=photo_colours)
    metric_path = out_dir / "exterior_metric.ply"
    mesh.export(metric_path)
    source_to_platform = np.eye(4)
    source_to_platform[:3, 3] = translation
    source_to_platform[:3, :3] = transform[:3, :3] * scale_factor
    texture_context_path = out_dir / "exterior_texture_context.json"
    texture_context_path.write_text(
        json.dumps(
            {
                "cameras": cameras,
                "source_from_platform": np.linalg.inv(source_to_platform).tolist(),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
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
            "texture_projection": texture_projection,
        },
        "note": (
            "COLMAP estimated cameras from overlapping facade photos and triangulated a "
            "connected exterior surface. The measured maximum dimension sets metric scale; "
            "registered cameras project the source photos into the persisted GLB atlas, and "
            "the report retains per-section registration and reprojection error."
        ),
    }
    return ExteriorResult(metric_path, coverage, details, texture_context_path)
