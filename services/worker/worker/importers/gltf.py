"""GLB / glTF importer (T-020): scene statistics, spec units are metres."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Any

import trimesh

from worker.importers.common import (
    PARSER,
    as_single_mesh,
    bbox_of,
    extent_warnings,
    mesh_stats,
    warn,
)
from worker.report import ImportMetadata, SceneStats, Severity, Warning

GLTF_SCALE_TO_MM = 1000.0
_GLB_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_MAX_JSON_BYTES = 64 * 1024 * 1024


def parse_gltf_file(path: Path, format_id: str) -> ImportMetadata:
    data = path.read_bytes()
    document = _document_json(data, format_id)
    warnings: list[Warning] = []

    if _has_external_uris(document):
        warnings.append(
            warn(
                "external_resources_ignored",
                Severity.warning,
                "glTF references external buffers/images; only embedded data is read",
            )
        )

    scene_stats = SceneStats(
        nodes=len(document.get("nodes", [])),
        meshes=len(document.get("meshes", [])),
        materials=len(document.get("materials", [])),
        textures=len(document.get("textures", [])),
        animations=len(document.get("animations", [])),
        cameras=len(document.get("cameras", [])),
        lights=len(document.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])),
        extensions_used=[str(e) for e in document.get("extensionsUsed", [])],
    )
    file_metadata = {
        str(k): str(v) for k, v in document.get("asset", {}).items() if isinstance(v, str | int)
    }

    # allow_remote=False and no resolver: external URIs cannot be fetched.
    try:
        loaded = trimesh.load(io.BytesIO(data), file_type=format_id, force="scene", process=False)
    except Exception as exc:  # trimesh raises assorted errors for missing buffers
        return ImportMetadata(
            format=format_id,
            representation="scene",
            unit_source="file",
            source_units="meters",
            scale_to_mm=GLTF_SCALE_TO_MM,
            bbox=None,
            scene=scene_stats,
            file_metadata=file_metadata,
            warnings=[
                *warnings,
                warn(
                    "geometry_unreadable",
                    Severity.error,
                    "scene geometry could not be decoded",
                    reason=type(exc).__name__,
                ),
            ],
            parser=PARSER,
        )

    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        warnings.append(warn("empty_geometry", Severity.error, "scene has no mesh geometry"))
        stats, bbox = None, None
    else:
        stats, mesh_warnings = mesh_stats(mesh, scale=GLTF_SCALE_TO_MM)
        bbox = bbox_of(mesh, scale=GLTF_SCALE_TO_MM)
        warnings.extend(mesh_warnings)
        warnings.extend(extent_warnings(bbox))

    return ImportMetadata(
        format=format_id,
        representation="scene",
        unit_source="file",
        source_units="meters",
        scale_to_mm=GLTF_SCALE_TO_MM,
        bbox=bbox,
        mesh=stats,
        scene=scene_stats,
        file_metadata=file_metadata,
        warnings=warnings,
        parser=PARSER,
    )


def _document_json(data: bytes, format_id: str) -> dict[str, Any]:
    if format_id == "glb":
        if len(data) < 20 or data[:4] != _GLB_MAGIC:
            raise ValueError("not a GLB container")
        chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
        if chunk_type != _JSON_CHUNK or chunk_length > _MAX_JSON_BYTES:
            raise ValueError("GLB has no valid JSON chunk")
        payload = data[20 : 20 + chunk_length]
    else:
        if len(data) > _MAX_JSON_BYTES:
            raise ValueError("glTF JSON too large")
        payload = data
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError("glTF root must be an object")
    return document


def _has_external_uris(document: dict[str, Any]) -> bool:
    for section in ("buffers", "images"):
        for item in document.get(section, []):
            uri = item.get("uri") if isinstance(item, dict) else None
            if isinstance(uri, str) and not uri.startswith("data:"):
                return True
    return False
