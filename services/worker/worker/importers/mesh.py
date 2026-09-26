"""STL (T-018), OBJ (T-019) and PLY importers: single-mesh formats without unit metadata."""

from __future__ import annotations

import io
import re
import struct
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

_STL_HEADER = 80
_STL_TRIANGLE = 50
# Containers someone might rename to .stl; checked before any parser sees the bytes.
_FOREIGN_MAGIC = {
    b"PK\x03\x04": "a ZIP archive (3MF, USDZ or similar)",
    b"glTF": "a binary glTF",
    b"ply\n": "a PLY file",
}


def check_stl_structure(data: bytes) -> None:
    """Refuse an STL whose bytes cannot be one, before trimesh sees it.

    Parser leniency is not a security boundary: trimesh 5.x reads a truncated binary STL,
    or a renamed ZIP, as an empty mesh instead of raising, so the refusal must be ours. A
    binary STL is exactly an 80-byte header, a triangle count and 50 bytes per triangle;
    trailing bytes are tolerated (some exporters pad), a shortfall is not. Anything else
    must be ASCII STL — starts with `solid`, has facets, and contains no NUL byte, which
    binary triangle data practically always does.
    """
    for magic, what in _FOREIGN_MAGIC.items():
        if data.startswith(magic):
            raise ValueError(f"format mismatch: the file is {what}, not an STL")
    if len(data) >= _STL_HEADER + 4:
        (claimed,) = struct.unpack_from("<I", data, _STL_HEADER)
        if len(data) >= _STL_HEADER + 4 + claimed * _STL_TRIANGLE:
            return
    head = data.lstrip()[:5].lower()
    if head == b"solid" and b"facet" in data and b"\x00" not in data:
        return
    if len(data) >= _STL_HEADER + 4:
        room = (len(data) - _STL_HEADER - 4) // _STL_TRIANGLE
        raise ValueError(
            f"malformed binary STL: header claims {claimed} triangles, the file holds {room}"
        )
    raise ValueError("not an STL: too short for a binary header and not ASCII STL text")


def parse_mesh_file(path: Path, format_id: str) -> ImportMetadata:
    data = path.read_bytes()
    if format_id == "stl":
        check_stl_structure(data)
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
