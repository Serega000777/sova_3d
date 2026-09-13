"""STL (T-018), OBJ (T-019) and PLY importers: single-mesh formats without unit metadata."""

from __future__ import annotations

import io
import re
from pathlib import Path

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

_OBJ_MTLLIB = re.compile(rb"^\s*mtllib\s+(.+?)\s*$", re.MULTILINE)
_OBJ_USEMTL = re.compile(rb"^\s*usemtl\s+(\S+)", re.MULTILINE)
_OBJ_OBJECT = re.compile(rb"^\s*[og]\s+\S", re.MULTILINE)
_MAX_REF_LEN = 200


def parse_mesh_file(path: Path, format_id: str) -> ImportMetadata:
    data = path.read_bytes()
    warnings: list[Warning] = [
        warn(
            "units_assumed",
            Severity.info,
            f"{format_id.upper()} carries no unit metadata; millimetres assumed",
        )
    ]
    material_refs: list[str] = []
    file_metadata: dict[str, str] = {}

    if format_id == "obj":
        material_refs, obj_warnings, objects = _scan_obj(data)
        warnings.extend(obj_warnings)
        if objects:
            file_metadata["objects"] = str(objects)

    # Load from memory with no resolver: referenced .mtl/texture files are never opened.
    loaded = trimesh.load(
        io.BytesIO(data),
        file_type=format_id,
        force="mesh",
        skip_materials=True,
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        return ImportMetadata(
            format=format_id,
            representation="mesh",
            unit_source="assumed",
            bbox=None,
            mesh=None,
            material_refs=material_refs,
            file_metadata=file_metadata,
            warnings=[*warnings, warn("empty_geometry", Severity.error, "no geometry found")],
            parser=PARSER,
        )

    stats, mesh_warnings = mesh_stats(mesh, scale=1.0)
    bbox = bbox_of(mesh, scale=1.0)
    return ImportMetadata(
        format=format_id,
        representation="mesh",
        unit_source="assumed",
        bbox=bbox,
        mesh=stats,
        material_refs=material_refs,
        file_metadata=file_metadata,
        warnings=[*warnings, *mesh_warnings, *extent_warnings(bbox)],
        parser=PARSER,
    )


def _scan_obj(data: bytes) -> tuple[list[str], list[Warning], int]:
    """Collect material library/material names as opaque strings; nothing is resolved."""
    refs: list[str] = []
    warnings: list[Warning] = []
    libs = [m.group(1) for m in _OBJ_MTLLIB.finditer(data)]
    names = [m.group(1) for m in _OBJ_USEMTL.finditer(data)]
    for raw in [*libs, *names]:
        text = raw.decode("utf-8", "replace")[:_MAX_REF_LEN]
        if text not in refs:
            refs.append(text)
    if libs:
        warnings.append(
            warn(
                "external_resources_ignored",
                Severity.info,
                "OBJ references material libraries; they are recorded but not loaded",
                count=len(libs),
            )
        )
    return refs, warnings, len(_OBJ_OBJECT.findall(data))
