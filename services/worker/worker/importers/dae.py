"""COLLADA (.dae) importer: mesh geometry scaled by the file's own declared unit.

Unlike OBJ/STL/PLY, COLLADA carries a real `<unit meter="...">` in `<asset>` — reading it
with pycollada directly (rather than trimesh's opaque `metadata["units"]` string) keeps the
same file-declared-unit path already used for 3MF, instead of assuming millimetres.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import collada
import trimesh

from worker.importers.common import (
    PARSER,
    as_single_mesh,
    bbox_of,
    extent_warnings,
    mesh_stats,
    warn,
)
from worker.report import ImportMetadata, Severity, Warning

_IGNORABLE = (
    collada.common.DaeError,
    collada.common.DaeIncompleteError,
    collada.common.DaeMalformedError,
    collada.common.DaeBrokenRefError,
    collada.common.DaeUnsupportedError,
)


def parse_dae_file(path: Path) -> ImportMetadata:
    data = path.read_bytes()
    warnings: list[Warning] = []

    try:
        doc = collada.Collada(io.BytesIO(data), ignore=list(_IGNORABLE))
        unit_meters = doc.assetInfo.unitmeter or 1.0
    except (collada.common.DaeError, ValueError, KeyError, AttributeError):
        unit_meters = 1.0
        warnings.append(
            warn("units_unknown", Severity.warning, "COLLADA asset info unreadable; assumed metres")
        )
    scale = unit_meters * 1000.0
    source_units = "meter" if math.isclose(unit_meters, 1.0) else f"{unit_meters:g} * meter"

    try:
        loaded = trimesh.load(io.BytesIO(data), file_type="dae", force="mesh", process=False)
    except Exception as exc:  # pycollada/trimesh raise assorted errors for malformed scenes
        return ImportMetadata(
            format="dae",
            representation="scene",
            unit_source="file",
            source_units=source_units,
            scale_to_mm=scale,
            bbox=None,
            mesh=None,
            warnings=[
                *warnings,
                warn(
                    "geometry_unreadable",
                    Severity.error,
                    "COLLADA geometry could not be decoded",
                    reason=type(exc).__name__,
                ),
            ],
            parser=PARSER,
        )

    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        warnings.append(warn("empty_geometry", Severity.error, "no mesh geometry found"))
        stats, bbox = None, None
    else:
        stats, mesh_warnings = mesh_stats(mesh, scale=scale)
        bbox = bbox_of(mesh, scale=scale)
        warnings.extend(mesh_warnings)
        warnings.extend(extent_warnings(bbox))

    return ImportMetadata(
        format="dae",
        representation="scene",
        unit_source="file",
        source_units=source_units,
        scale_to_mm=scale,
        bbox=bbox,
        mesh=stats,
        warnings=warnings,
        parser=PARSER,
    )
