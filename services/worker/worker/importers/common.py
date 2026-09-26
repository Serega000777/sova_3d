"""Shared mesh statistics and quality-gate warnings built on trimesh."""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

from worker.report import BBox, MeshStats, Severity, Warning

PARSER = f"trimesh/{trimesh.__version__}"

GLTF_FORMATS = frozenset({"glb", "gltf"})
# glTF (and X3D/VRML, FBX by default) are Y-up; the platform is Z-up: (x, y, z) -> (x, -z, y),
# +90 degrees about X. Its transpose goes back.
Y_UP_TO_Z_UP = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)
Z_UP_TO_Y_UP = Y_UP_TO_Z_UP.T
ZERO_AREA_MM2 = 1e-9

UNIT_TO_MM: dict[str, float] = {
    "micron": 0.001,
    "micrometer": 0.001,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "mm": 1.0,
    "centimeter": 10.0,
    "cm": 10.0,
    "meter": 1000.0,
    "meters": 1000.0,
    "m": 1000.0,
    "inch": 25.4,
    "in": 25.4,
    "foot": 304.8,
    "ft": 304.8,
}


def to_platform_axes(mesh: trimesh.Trimesh, format_id: str | None) -> trimesh.Trimesh:
    """A glTF mesh turned from the spec's Y-up to the platform's Z-up, in place."""
    if format_id in GLTF_FORMATS:
        mesh.apply_transform(Y_UP_TO_Z_UP)
    return mesh


def warn(code: str, severity: Severity, message: str, **details: Any) -> Warning:
    return Warning(code=code, severity=severity, message=message, details=details)


def as_single_mesh(geometry: Any) -> trimesh.Trimesh | None:
    """Flatten a Trimesh or Scene (transforms applied) into one mesh for global stats."""
    if isinstance(geometry, trimesh.Trimesh):
        return geometry
    if isinstance(geometry, trimesh.Scene):
        if geometry.is_empty:
            return None
        merged = geometry.to_geometry()
        return merged if isinstance(merged, trimesh.Trimesh) else None
    return None


def bbox_of(mesh: trimesh.Trimesh, scale: float) -> BBox | None:
    if mesh.is_empty or mesh.bounds is None:
        return None
    lo, hi = (np.asarray(mesh.bounds, dtype=float) * scale).tolist()
    return BBox(min=(lo[0], lo[1], lo[2]), max=(hi[0], hi[1], hi[2]))


def mesh_stats(mesh: trimesh.Trimesh, scale: float) -> tuple[MeshStats, list[Warning]]:
    warnings: list[Warning] = []
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)

    if not np.all(np.isfinite(vertices)):
        warnings.append(
            warn("nan_coordinates", Severity.error, "mesh contains NaN or infinite coordinates")
        )
        # Drop them so the remaining stats are still computable.
        keep = np.all(np.isfinite(vertices), axis=1)
        mesh = mesh.copy()
        mesh.update_vertices(keep)
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces)

    # Formats like STL store a triangle soup; merge coincident vertices so topology
    # (watertightness, bodies, Euler number) reflects the surface, not the encoding.
    if len(faces):
        mesh = mesh.copy()
        mesh.merge_vertices()
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces)

    face_areas = np.asarray(mesh.area_faces, dtype=float) if len(faces) else np.zeros(0)
    degenerate = int(np.count_nonzero(face_areas * scale * scale < ZERO_AREA_MM2))
    unique_faces = len(np.unique(np.sort(faces, axis=1), axis=0)) if len(faces) else 0
    duplicate = int(len(faces) - unique_faces)

    watertight = bool(mesh.is_watertight) if len(faces) else False
    winding = bool(mesh.is_winding_consistent) if len(faces) else False
    volume = float(mesh.volume) * scale**3 if watertight and winding else None

    stats = MeshStats(
        vertices=int(len(vertices)),
        faces=int(len(faces)),
        bodies=int(mesh.body_count) if len(faces) else 0,
        watertight=watertight,
        winding_consistent=winding,
        volume_mm3=volume,
        surface_area_mm2=float(mesh.area) * scale * scale if len(faces) else 0.0,
        euler_number=int(mesh.euler_number) if len(faces) else 0,
        degenerate_faces=degenerate,
        duplicate_faces=duplicate,
    )

    if stats.faces == 0:
        warnings.append(warn("empty_geometry", Severity.error, "mesh has no faces"))
        return stats, warnings
    if not watertight:
        warnings.append(
            warn("not_watertight", Severity.warning, "mesh is not watertight (open edges)")
        )
    if not winding:
        warnings.append(
            warn("inconsistent_winding", Severity.warning, "face winding is inconsistent")
        )
    if degenerate:
        warnings.append(
            warn(
                "degenerate_faces",
                Severity.warning,
                "mesh has zero-area faces",
                count=degenerate,
            )
        )
    if duplicate:
        warnings.append(
            warn("duplicate_faces", Severity.warning, "mesh has duplicate faces", count=duplicate)
        )
    if stats.bodies > 1:
        warnings.append(
            warn("multiple_bodies", Severity.info, "mesh has several bodies", count=stats.bodies)
        )
    return stats, warnings


def extent_warnings(bbox: BBox | None) -> list[Warning]:
    if bbox is None:
        return []
    zero_axes = [axis for axis, size in zip("xyz", bbox.size, strict=True) if size <= 0]
    if zero_axes:
        return [
            warn(
                "zero_extent",
                Severity.warning,
                "bounding box has zero extent on some axes",
                axes="".join(zero_axes),
            )
        ]
    return []


def units_from(declared: str | None) -> tuple[float, str | None]:
    """Return (scale_to_mm, normalized source unit) or (1.0, None) when unknown."""
    if not declared:
        return 1.0, None
    key = declared.strip().lower()
    if key in UNIT_TO_MM:
        return UNIT_TO_MM[key], key
    return 1.0, None
