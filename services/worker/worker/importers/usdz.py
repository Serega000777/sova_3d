"""USDZ importer/geometry helpers (F-014/F-015): Apple's AR Quick Look container.

USDZ is a ZIP archive under the hood (uncompressed per Apple's spec, but we do not require
that — only that it is safe to open), so the same archive defenses as 3MF apply first. A
stage can have several Mesh prims under transforms; they are traversed, their world
transform applied, and merged into one mesh — this platform's single-body convention,
same as every other scene format (GLB, DAE).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom

from worker.importers.common import (
    PARSER,
    bbox_of,
    extent_warnings,
    mesh_stats,
    warn,
)
from worker.importers.zipsafe import DEFAULT_ARCHIVE_LIMITS, ArchiveLimits, validate_zip
from worker.report import ImportMetadata, Severity, Warning

try:
    import trimesh
except ImportError:  # pragma: no cover - trimesh is a hard dependency elsewhere
    trimesh = None  # type: ignore[assignment]


def _triangulate_face(count: int, cursor: int) -> list[tuple[int, int, int]]:
    """Fan triangulation from the face's own first vertex, as positions in the flat
    `faceVertexIndices` array (the caller resolves these to actual vertex indices). Exact for
    triangles/quads/any convex polygon; an honest approximation (not a general ear-clipper)
    for rarer concave N-gons, flagged separately by the caller."""
    return [(cursor, cursor + i, cursor + i + 1) for i in range(1, count - 1)]


def _merge_meshes(stage: Usd.Stage) -> tuple[np.ndarray, np.ndarray, bool]:
    """(vertices, triangle faces, had_ngon) across every Mesh prim, world-transformed."""
    vertex_parts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    had_ngon = False
    offset = 0

    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        if not points or not counts or not indices:
            continue

        matrix = UsdGeom.Xformable(mesh).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        world = np.array([matrix.Transform((p[0], p[1], p[2])) for p in points], dtype=float)
        vertex_parts.append(world)

        cursor = 0
        for count in counts:
            if count == 3:
                faces.append(np.array(indices[cursor : cursor + 3], dtype=int) + offset)
            elif count > 3:
                had_ngon = had_ngon or count > 4
                for tri in _triangulate_face(count, cursor):
                    faces.append(np.array([indices[i] for i in tri], dtype=int) + offset)
            cursor += count
        offset += len(points)

    if not vertex_parts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int), False
    vertices = np.concatenate(vertex_parts, axis=0)
    face_array = np.array(faces, dtype=int) if faces else np.zeros((0, 3), dtype=int)
    return vertices, face_array, had_ngon


def load_mesh(path: Path, limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS) -> trimesh.Trimesh:
    """Every Mesh prim, world-transformed and merged into one — for the exporter's
    convert-to-another-format path, which wants a plain mesh and raises on any problem."""
    assert trimesh is not None
    validate_zip(path, limits)
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError("USD stage could not be opened")
    vertices, faces, _ = _merge_meshes(stage)
    if len(faces) == 0:
        raise ValueError("USDZ has no mesh geometry")
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def load_mesh_mm(path: Path, limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS) -> trimesh.Trimesh:
    """`load_mesh`, scaled by the stage's own `metersPerUnit` (RoomPlan's export is metres;
    a bare `load_mesh` would hand back a model a thousand times too small)."""
    assert trimesh is not None
    validate_zip(path, limits)
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError("USD stage could not be opened")
    vertices, faces, _ = _merge_meshes(stage)
    if len(faces) == 0:
        raise ValueError("USDZ has no mesh geometry")
    scale = UsdGeom.GetStageMetersPerUnit(stage) * 1000.0
    return trimesh.Trimesh(vertices=vertices * scale, faces=faces, process=False)


def parse_usdz_file(path: Path, limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS) -> ImportMetadata:
    assert trimesh is not None
    warnings: list[Warning] = []
    try:
        validate_zip(path, limits)
    except ValueError as exc:
        return ImportMetadata(
            format="usdz",
            representation="scene",
            unit_source="assumed",
            bbox=None,
            mesh=None,
            warnings=[warn("unsafe_archive", Severity.error, str(exc))],
            parser=PARSER,
        )

    try:
        stage = Usd.Stage.Open(str(path))
        if stage is None:
            raise ValueError("USD stage could not be opened")
        meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
        vertices, faces, had_ngon = _merge_meshes(stage)
    except Exception as exc:  # USD raises assorted C++-bound errors for malformed files
        return ImportMetadata(
            format="usdz",
            representation="scene",
            unit_source="assumed",
            bbox=None,
            mesh=None,
            warnings=[
                warn(
                    "geometry_unreadable",
                    Severity.error,
                    "USDZ stage could not be decoded",
                    reason=type(exc).__name__,
                )
            ],
            parser=PARSER,
        )

    scale = meters_per_unit * 1000.0 if meters_per_unit else 1000.0
    source_units = (
        "meter" if math.isclose(meters_per_unit or 1.0, 1.0) else f"{meters_per_unit:g} * meter"
    )
    if had_ngon:
        warnings.append(
            warn(
                "ngon_triangulated",
                Severity.warning,
                "faces with more than 4 vertices were fan-triangulated from their first "
                "vertex; concave polygons may not triangulate exactly",
            )
        )

    if len(faces) == 0:
        warnings.append(warn("empty_geometry", Severity.error, "no mesh geometry found"))
        stats, bbox = None, None
    else:
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        stats, mesh_warnings = mesh_stats(mesh, scale=scale)
        bbox = bbox_of(mesh, scale=scale)
        warnings.extend(mesh_warnings)
        warnings.extend(extent_warnings(bbox))

    return ImportMetadata(
        format="usdz",
        representation="scene",
        unit_source="file",
        source_units=source_units,
        scale_to_mm=scale,
        bbox=bbox,
        mesh=stats,
        warnings=warnings,
        parser=PARSER,
    )


def write_usdz(mesh: trimesh.Trimesh, output_path: Path) -> None:
    """Write one mesh as a USDZ: explicit Z-up and mm-per-unit, so a round trip through
    this same reader — or any spec-compliant one — needs no assumption."""
    import tempfile

    from pxr import UsdUtils

    with tempfile.TemporaryDirectory(prefix="usdz-stage-") as tmp_dir:
        usdc_path = Path(tmp_dir) / "model.usdc"
        stage = Usd.Stage.CreateNew(str(usdc_path))
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 0.001)  # canonical mm
        prim = UsdGeom.Mesh.Define(stage, "/Model")
        prim.CreatePointsAttr([tuple(v) for v in mesh.vertices])
        prim.CreateFaceVertexCountsAttr([3] * len(mesh.faces))
        prim.CreateFaceVertexIndicesAttr([int(i) for i in mesh.faces.flatten()])
        prim.CreateNormalsAttr([tuple(n) for n in mesh.vertex_normals[mesh.faces.flatten()]])
        stage.SetDefaultPrim(prim.GetPrim())
        stage.GetRootLayer().Save()
        if not UsdUtils.CreateNewUsdzPackage(str(usdc_path), str(output_path)):
            raise ValueError("USD could not package the model as USDZ")
