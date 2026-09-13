"""3MF importer (T-021): ZIP container defenses, hardened XML, objects/build metadata."""

from __future__ import annotations

import io
from pathlib import Path

import trimesh
from lxml import etree

from worker.importers.common import (
    PARSER,
    as_single_mesh,
    bbox_of,
    extent_warnings,
    mesh_stats,
    units_from,
    warn,
)
from worker.importers.zipsafe import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveLimits,
    read_member,
    validate_zip,
)
from worker.report import BuildItem, ImportMetadata, ObjectStats, Severity, Warning

MODEL_MEMBER = "3D/3dmodel.model"
_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_MAX_MODEL_XML = 256 * 1024 * 1024

# No DTD/entities (XXE, billion laughs), no network, bounded tree depth.
_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    huge_tree=False,
    remove_comments=True,
)


def parse_3mf_file(path: Path, limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS) -> ImportMetadata:
    entries = validate_zip(path, limits)
    names = {e.filename for e in entries}
    if MODEL_MEMBER not in names:
        raise ValueError("3MF package has no 3D/3dmodel.model")

    xml_bytes = read_member(path, MODEL_MEMBER, _MAX_MODEL_XML)
    if b"<!DOCTYPE" in xml_bytes[:4096].upper():
        raise ValueError("3MF model XML declares a DOCTYPE; rejected")
    root = etree.fromstring(xml_bytes, _XML_PARSER)

    declared_unit = root.get("unit") or "millimeter"
    scale, source_units = units_from(declared_unit)
    warnings: list[Warning] = []
    if source_units is None:
        warnings.append(
            warn("units_unknown", Severity.warning, "unrecognised 3MF unit", unit=declared_unit)
        )
        scale, source_units = 1.0, "millimeter"

    file_metadata = {
        str(m.get("name")): (m.text or "").strip()
        for m in root.iter(f"{_NS}metadata")
        if m.get("name")
    }
    objects = [
        ObjectStats(
            id=str(obj.get("id")),
            name=obj.get("name"),
            type=obj.get("type") or "model",
            vertices=sum(1 for _ in obj.iter(f"{_NS}vertex")),
            triangles=sum(1 for _ in obj.iter(f"{_NS}triangle")),
        )
        for obj in root.iter(f"{_NS}object")
    ]
    build_items = [
        BuildItem(
            object_id=str(item.get("objectid")), has_transform=item.get("transform") is not None
        )
        for item in root.iter(f"{_NS}item")
    ]
    if not build_items:
        warnings.append(warn("no_build_items", Severity.warning, "3MF build section is empty"))

    mesh = None
    if build_items:
        try:
            loaded = trimesh.load(io.BytesIO(path.read_bytes()), file_type="3mf", force="scene")
        except (KeyError, ValueError, IndexError) as exc:
            warnings.append(
                warn(
                    "geometry_unreadable",
                    Severity.error,
                    "3MF build geometry could not be decoded",
                    reason=type(exc).__name__,
                )
            )
        else:
            mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        warnings.append(warn("empty_geometry", Severity.error, "no mesh geometry in build"))
        stats, bbox = None, None
    else:
        stats, mesh_warnings = mesh_stats(mesh, scale=scale)
        bbox = bbox_of(mesh, scale=scale)
        warnings.extend(mesh_warnings)
        warnings.extend(extent_warnings(bbox))

    return ImportMetadata(
        format="3mf",
        representation="mesh",
        unit_source="file",
        source_units=source_units,
        scale_to_mm=scale,
        bbox=bbox,
        mesh=stats,
        objects=objects,
        build_items=build_items,
        file_metadata=file_metadata,
        warnings=warnings,
        parser=PARSER,
    )
