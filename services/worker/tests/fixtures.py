"""Generated fixtures: small but real files for each importer, plus hostile variants."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

BOX_MM = (20.0, 10.0, 5.0)


def box() -> trimesh.Trimesh:
    mesh: trimesh.Trimesh = trimesh.creation.box(extents=BOX_MM)
    return mesh


def export_bytes(geometry: Any, file_type: str) -> bytes:
    exported = geometry.export(file_type=file_type)
    return exported.encode() if isinstance(exported, str) else bytes(exported)


def write_stl_binary(path: Path) -> Path:
    path.write_bytes(export_bytes(box(), "stl"))
    return path


def write_stl_ascii(path: Path) -> Path:
    path.write_bytes(export_bytes(box(), "stl_ascii"))
    return path


def write_stl_open(path: Path) -> Path:
    """Box with one face removed: not watertight."""
    mesh = box()
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)
    path.write_bytes(export_bytes(mesh, "stl"))
    return path


def write_dae(path: Path, *, unit_meter: float | None = None) -> Path:
    """COLLADA export of the fixture box; `unit_meter` overrides/removes the <asset><unit>."""
    data = export_bytes(box(), "dae")
    if unit_meter is not None:
        tag = f'<unit meter="{unit_meter}" name="custom"/>'.encode()
        data = data.replace(b"</asset>", tag + b"</asset>")
    path.write_bytes(data)
    return path


def write_usdz(path: Path, *, meters_per_unit: float = 0.001) -> Path:
    """A USDZ package of the fixture box, built directly with pxr at a chosen unit scale."""
    import tempfile

    from pxr import Usd, UsdGeom, UsdUtils

    mesh = box()
    with tempfile.TemporaryDirectory(prefix="fixture-usdz-") as tmp_dir:
        usdc_path = Path(tmp_dir) / "model.usdc"
        stage = Usd.Stage.CreateNew(str(usdc_path))
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
        prim = UsdGeom.Mesh.Define(stage, "/Model")
        prim.CreatePointsAttr([tuple(v) for v in mesh.vertices])
        prim.CreateFaceVertexCountsAttr([3] * len(mesh.faces))
        prim.CreateFaceVertexIndicesAttr([int(i) for i in mesh.faces.flatten()])
        stage.SetDefaultPrim(prim.GetPrim())
        stage.GetRootLayer().Save()
        if not UsdUtils.CreateNewUsdzPackage(str(usdc_path), str(path)):
            raise RuntimeError("test fixture: USD could not package the model as USDZ")
    return path


def write_stl_nan(path: Path) -> Path:
    """Binary STL whose first vertex is NaN."""
    data = bytearray(export_bytes(box(), "stl"))
    # header 80 + count 4, then per triangle: normal(12) + 3 vertices(36) + attr(2)
    offset = 84 + 12
    data[offset : offset + 4] = struct.pack("<f", float("nan"))
    path.write_bytes(bytes(data))
    return path


def write_obj_with_materials(path: Path) -> Path:
    obj = export_bytes(box(), "obj").decode()
    text = "mtllib ../../etc/passwd.mtl\no box\nusemtl steel\n" + obj + "\nusemtl plastic\n"
    path.write_text(text, encoding="utf-8")
    return path


def write_glb(path: Path) -> Path:
    scene = trimesh.Scene(box())  # glTF units are metres: 20 -> 20000 mm
    path.write_bytes(export_bytes(scene, "glb"))
    return path


def write_gltf_external(path: Path) -> Path:
    """glTF JSON pointing at a buffer file we never ship."""
    doc = {
        "asset": {"version": "2.0", "generator": "fixture"},
        "buffers": [{"uri": "missing.bin", "byteLength": 36}],
        "bufferViews": [{"buffer": 0, "byteLength": 36}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def threemf_model_xml(unit: str = "millimeter", with_build: bool = True) -> bytes:
    mesh = box()
    verts = "".join(
        f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in np.asarray(mesh.vertices).tolist()
    )
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces.tolist())
    build = (
        '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build>'
        if with_build
        else "<build/>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="{unit}" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<metadata name="Title">Fixture box</metadata>'
        '<resources><object id="1" name="box" type="model"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        "</mesh></object></resources>"
        f"{build}</model>"
    ).encode()


def write_3mf(
    path: Path, model_xml: bytes | None = None, extra: dict[str, bytes] | None = None
) -> Path:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml or threemf_model_xml())
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    path.write_bytes(buffer.getvalue())
    return path


def write_zip_bomb(path: Path) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", b"\0" * (64 * 1024 * 1024))  # ratio ~ 1000:1
    path.write_bytes(buffer.getvalue())
    return path


def write_zip_traversal(path: Path) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../evil.model", b"x")
        archive.writestr("3D/3dmodel.model", threemf_model_xml())
    path.write_bytes(buffer.getvalue())
    return path


def write_3mf_xxe(path: Path) -> Path:
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE model [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        b'<metadata name="Title">&xxe;</metadata><resources/><build/></model>'
    )
    return write_3mf(path, model_xml=xml)
