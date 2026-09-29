"""Alembic Ogawa static PolyMesh import/export (F-014/F-015).

Alembic's supported Python bindings are wrappers around the native C++ library; there is no
practical pure-Python wheel for the worker's Python version.  This module therefore implements
the small, documented Ogawa/AbcCoreOgawa subset needed for a static ``AbcGeom_PolyMesh_v1``:
positions, polygon indices/counts and optional normal/UV geometry parameters.

Only the first sample is read.  Object animation, skeletons, materials, cameras, curves, SubD,
NuPatch and HDF5-backed Alembic archives are deliberately outside this subset.  Input is still
hostile: every offset and declared size is checked before slicing, group/property/object counts
and nesting are bounded, and geometry allocation has explicit vertex/triangle limits.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh

from worker.importers.common import (
    PARSER,
    Y_UP_TO_Z_UP,
    Z_UP_TO_Y_UP,
    bbox_of,
    extent_warnings,
    mesh_stats,
    warn,
)
from worker.report import ImportMetadata, Severity, Warning

MAGIC = b"Ogawa"
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
DATA_BIT = 1 << 63
ADDRESS_MASK = DATA_BIT - 1
EMPTY_DATA = DATA_BIT

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_GROUP_CHILDREN = 2_000_000
MAX_GROUPS = 500_000
MAX_DEPTH = 128
MAX_PROPERTIES = 100_000
MAX_OBJECTS = 100_000
MAX_SAMPLE_BYTES = 256 * 1024 * 1024
MAX_VERTICES = 10_000_000
MAX_TRIANGLES = 5_000_000

_POD_DTYPES: dict[int, np.dtype[Any]] = {
    0: np.dtype("?"),
    1: np.dtype("u1"),
    2: np.dtype("i1"),
    3: np.dtype("<u2"),
    4: np.dtype("<i2"),
    5: np.dtype("<u4"),
    6: np.dtype("<i4"),
    7: np.dtype("<u8"),
    8: np.dtype("<i8"),
    9: np.dtype("<f2"),
    10: np.dtype("<f4"),
    11: np.dtype("<f8"),
}


@dataclass(frozen=True, slots=True)
class _Group:
    address: int
    children: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Property:
    name: str
    kind: int  # 0 compound, 1 scalar, 2 array
    pod: int = 127
    extent: int = 0
    samples: int = 0
    metadata: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _Object:
    name: str
    metadata: dict[str, str]


class _Cursor:
    def __init__(self, data: bytes, what: str) -> None:
        self.data = data
        self.offset = 0
        self.what = what

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise ValueError(f"{self.what} ends in the middle of a declared field")
        result = self.data[self.offset : self.offset + size]
        self.offset += size
        return result

    def uint(self, size: int) -> int:
        if size not in (1, 2, 4):
            raise ValueError(f"invalid integer width {size} in {self.what}")
        return int.from_bytes(self.take(size), "little")

    def text(self, size: int) -> str:
        try:
            return self.take(size).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"invalid UTF-8 in {self.what}") from exc


class _Archive:
    def __init__(self, data: bytes) -> None:
        if data.startswith(HDF5_MAGIC):
            raise ValueError("HDF5 Alembic is not supported; re-export the archive as Ogawa")
        if not data.startswith(MAGIC):
            raise ValueError("not an Alembic Ogawa file (invalid magic number)")
        if len(data) < 16:
            raise ValueError("truncated Alembic Ogawa header")
        if data[5] != 0xFF:
            raise ValueError("the Alembic Ogawa archive was not finalized")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("the Alembic file is larger than the importer accepts")
        self.data = data
        self.groups: dict[int, _Group] = {}
        self.indexed_metadata: list[dict[str, str]] = [{}]
        self.animated = False
        root_address = self._u64(8, "root group pointer")
        self.root = self.group(root_address)
        if len(self.root.children) < 6:
            raise ValueError("Alembic root group is missing required archive records")
        if any(not self.is_data(self.root.children[i]) for i in (0, 1, 3, 4, 5)):
            raise ValueError("Alembic root group has invalid record types")
        if self.is_data(self.root.children[2]):
            raise ValueError("Alembic root object is not an Ogawa group")
        self._read_time_samplings(self.payload(self.root.children[4]))
        self.indexed_metadata = self._metadata_table(self.payload(self.root.children[5]))

    @staticmethod
    def is_data(reference: int) -> bool:
        return bool(reference & DATA_BIT)

    def _u64(self, offset: int, what: str) -> int:
        if offset < 0 or offset + 8 > len(self.data):
            raise ValueError(f"Alembic file is truncated at {what}")
        return int(struct.unpack_from("<Q", self.data, offset)[0])

    def group(self, reference: int, depth: int = 0) -> _Group:
        if depth > MAX_DEPTH:
            raise ValueError(f"Alembic groups nest deeper than {MAX_DEPTH} levels")
        if self.is_data(reference):
            raise ValueError("Alembic data record was referenced as a group")
        address = reference & ADDRESS_MASK
        if address == 0:
            return _Group(0, ())
        cached = self.groups.get(address)
        if cached is not None:
            return cached
        if len(self.groups) >= MAX_GROUPS:
            raise ValueError("Alembic archive has too many groups")
        count = self._u64(address, "group child count")
        if count == 0 or count > MAX_GROUP_CHILDREN:
            raise ValueError("Alembic group declares an invalid child count")
        table_end = address + 8 + count * 8
        if table_end > len(self.data):
            raise ValueError("Alembic group child table runs past the end of the file")
        children = struct.unpack_from(f"<{count}Q", self.data, address + 8)
        group = _Group(address, children)
        self.groups[address] = group
        return group

    def payload(self, reference: int) -> bytes:
        if not self.is_data(reference):
            raise ValueError("Alembic group record was referenced as data")
        address = reference & ADDRESS_MASK
        if address == 0:
            return b""
        size = self._u64(address, "data size")
        if size > MAX_SAMPLE_BYTES:
            raise ValueError("an Alembic data record is larger than the importer accepts")
        end = address + 8 + size
        if end > len(self.data):
            raise ValueError("an Alembic data record's declared size exceeds the file")
        return self.data[address + 8 : end]

    @staticmethod
    def _tokens(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in text.split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                result[key] = value
        return result

    def _metadata(self, cursor: _Cursor, index: int, width: int) -> dict[str, str]:
        if index == 0:
            return {}
        if index == 0xFF:
            size = cursor.uint(width)
            return self._tokens(cursor.text(size))
        if index >= len(self.indexed_metadata):
            raise ValueError("Alembic metadata index is outside the metadata table")
        return self.indexed_metadata[index]

    def _metadata_table(self, data: bytes) -> list[dict[str, str]]:
        cursor = _Cursor(data, "Alembic metadata table")
        result: list[dict[str, str]] = [{}]
        while cursor.offset < len(data):
            size = cursor.uint(1)
            result.append(self._tokens(cursor.text(size)))
            if len(result) > 255:
                raise ValueError("Alembic metadata table has too many records")
        return result

    def _read_time_samplings(self, data: bytes) -> None:
        cursor = _Cursor(data, "Alembic time-sampling table")
        while cursor.offset < len(data):
            max_samples = cursor.uint(4)
            cursor.take(8)  # time per cycle
            stored = cursor.uint(4)
            if stored == 0 or stored > 1_000_000:
                raise ValueError("Alembic time sampling declares an invalid sample count")
            cursor.take(stored * 8)
            self.animated = self.animated or max_samples > 1

    def object_headers(self, group: _Group) -> list[_Object]:
        if not group.children or not self.is_data(group.children[-1]):
            return []
        data = self.payload(group.children[-1])
        if len(data) < 32:
            raise ValueError("Alembic object header record is missing its hashes")
        cursor = _Cursor(data[:-32], "Alembic object headers")
        result: list[_Object] = []
        while cursor.offset < len(cursor.data):
            name = cursor.text(cursor.uint(4))
            metadata = self._metadata(cursor, cursor.uint(1), 4)
            result.append(_Object(name, metadata))
            if len(result) > MAX_OBJECTS:
                raise ValueError("Alembic archive has too many objects")
        return result

    def property_headers(self, group: _Group) -> list[_Property]:
        if not group.children or not self.is_data(group.children[-1]):
            return []
        cursor = _Cursor(self.payload(group.children[-1]), "Alembic property headers")
        result: list[_Property] = []
        while cursor.offset < len(cursor.data):
            info = cursor.uint(4)
            raw_kind = info & 0x3
            kind = 0 if raw_kind == 0 else 1 if raw_kind == 1 else 2
            hint = (info >> 2) & 0x3
            if hint > 2:
                raise ValueError("Alembic property uses an invalid integer-size hint")
            width = (1, 2, 4)[hint]
            pod = 127
            extent = 0
            samples = 0
            if kind:
                pod = (info >> 4) & 0xF
                extent = (info >> 12) & 0xFF
                if pod not in _POD_DTYPES or extent == 0:
                    raise ValueError("Alembic property has an unsupported data type")
                samples = cursor.uint(width)
                if samples > 1_000_000:
                    raise ValueError("Alembic property declares too many samples")
                if info & 0x0200:
                    cursor.uint(width)
                    cursor.uint(width)
                if info & 0x0100:
                    cursor.uint(width)
                self.animated = self.animated or samples > 1
            name = cursor.text(cursor.uint(width))
            metadata = self._metadata(cursor, (info >> 20) & 0xFF, width)
            result.append(_Property(name, kind, pod, extent, samples, metadata))
            if len(result) > MAX_PROPERTIES:
                raise ValueError("Alembic object has too many properties")
        return result

    def sample(self, group: _Group, prop: _Property) -> np.ndarray:
        if prop.kind not in (1, 2) or prop.samples < 1 or not group.children:
            raise ValueError(f"Alembic property {prop.name!r} has no sample")
        data = self.payload(group.children[0])
        if len(data) < 16:
            raise ValueError(f"Alembic property {prop.name!r} has a truncated sample digest")
        raw = data[16:]
        dtype = _POD_DTYPES[prop.pod]
        stride = dtype.itemsize * prop.extent
        if len(raw) % stride:
            raise ValueError(f"Alembic property {prop.name!r} sample size is inconsistent")
        count = len(raw) // stride
        if count > MAX_VERTICES * 6:
            raise ValueError(f"Alembic property {prop.name!r} has too many values")
        return np.frombuffer(raw, dtype=dtype).reshape((-1, prop.extent)).copy()


def _property_map(archive: _Archive, group: _Group) -> dict[str, tuple[_Property, _Group]]:
    headers = archive.property_headers(group)
    data_children = len(group.children) - (
        1 if group.children and archive.is_data(group.children[-1]) else 0
    )
    if len(headers) > data_children:
        raise ValueError("Alembic property headers outnumber their property groups")
    return {
        header.name: (header, archive.group(group.children[index], 1))
        for index, header in enumerate(headers)
    }


def _geom_param(
    archive: _Archive, item: tuple[_Property, _Group] | None, extent: int
) -> tuple[np.ndarray, dict[str, str]] | None:
    if item is None:
        return None
    prop, group = item
    metadata = prop.metadata or {}
    if prop.kind == 2:
        if prop.extent != extent:
            raise ValueError(f"Alembic geometry parameter {prop.name!r} has the wrong extent")
        return archive.sample(group, prop), metadata
    if prop.kind != 0:
        raise ValueError(f"Alembic geometry parameter {prop.name!r} is neither array nor indexed")
    children = _property_map(archive, group)
    values_item = children.get(".vals")
    if values_item is None:
        raise ValueError(f"Alembic indexed parameter {prop.name!r} has no .vals")
    values_prop, values_group = values_item
    if values_prop.kind != 2 or values_prop.extent != extent:
        raise ValueError(f"Alembic indexed parameter {prop.name!r} has invalid .vals")
    values = archive.sample(values_group, values_prop)
    indices_item = children.get(".indices")
    if indices_item is None:
        return values, metadata
    indices_prop, indices_group = indices_item
    if indices_prop.kind != 2 or indices_prop.extent != 1 or indices_prop.pod not in (5, 6, 7, 8):
        raise ValueError(f"Alembic indexed parameter {prop.name!r} has invalid .indices")
    indices = archive.sample(indices_group, indices_prop).reshape(-1).astype(np.int64)
    if np.any(indices < 0) or np.any(indices >= len(values)):
        raise ValueError(f"Alembic indexed parameter {prop.name!r} points outside .vals")
    return values[indices], metadata


def _scope_value(
    param: tuple[np.ndarray, dict[str, str]] | None,
    vertex: int,
    face: int,
    corner: int,
    vertex_count: int,
    face_count: int,
    corner_count: int,
) -> np.ndarray | None:
    if param is None:
        return None
    values, metadata = param
    scope = metadata.get("geoScope", "")
    if len(values) == 1 or scope == "con":
        return cast(np.ndarray, values[0])
    if len(values) == corner_count or scope == "fvr":
        if corner >= len(values):
            raise ValueError("Alembic face-varying geometry parameter has too few values")
        return cast(np.ndarray, values[corner])
    if len(values) == face_count or scope == "uni":
        if face >= len(values):
            raise ValueError("Alembic uniform geometry parameter has too few values")
        return cast(np.ndarray, values[face])
    if len(values) == vertex_count or scope in ("vtx", "varying"):
        if vertex >= len(values):
            raise ValueError("Alembic vertex geometry parameter has too few values")
        return cast(np.ndarray, values[vertex])
    raise ValueError("Alembic geometry parameter cardinality does not match its scope")


def _mesh_from_geom(archive: _Archive, group: _Group) -> trimesh.Trimesh:
    props = _property_map(archive, group)
    required = ("P", ".faceIndices", ".faceCounts")
    if any(name not in props for name in required):
        raise ValueError("Alembic PolyMesh is missing P, .faceIndices or .faceCounts")
    points_prop, points_group = props["P"]
    index_prop, index_group = props[".faceIndices"]
    count_prop, count_group = props[".faceCounts"]
    if points_prop.kind != 2 or points_prop.extent != 3 or points_prop.pod not in (10, 11):
        raise ValueError("Alembic P must be a float32/float64 vector3 array")
    if index_prop.kind != 2 or index_prop.extent != 1 or index_prop.pod not in (6, 8):
        raise ValueError("Alembic .faceIndices must be an int32/int64 array")
    if count_prop.kind != 2 or count_prop.extent != 1 or count_prop.pod not in (6, 8):
        raise ValueError("Alembic .faceCounts must be an int32/int64 array")

    points = archive.sample(points_group, points_prop).astype(np.float64)
    indices = archive.sample(index_group, index_prop).reshape(-1).astype(np.int64)
    counts = archive.sample(count_group, count_prop).reshape(-1).astype(np.int64)
    if len(points) > MAX_VERTICES:
        raise ValueError("Alembic PolyMesh has too many vertices")
    if len(counts) > MAX_TRIANGLES:
        raise ValueError("Alembic PolyMesh has too many faces")
    if np.any(counts < 3):
        raise ValueError("Alembic PolyMesh contains a face with fewer than three vertices")
    index_count = sum(int(value) for value in counts)
    if index_count != len(indices):
        raise ValueError("Alembic face counts do not match the face-index array")
    if np.any(indices < 0) or np.any(indices >= len(points)):
        raise ValueError("Alembic face index points outside P")
    triangle_count = index_count - 2 * len(counts)
    if triangle_count > MAX_TRIANGLES:
        raise ValueError("Alembic PolyMesh has too many triangles")

    uv = _geom_param(archive, props.get("uv"), 2)
    normals = _geom_param(archive, props.get("N"), 3)
    triangles: list[tuple[int, int, int]] = []
    triangle_corners: list[tuple[int, int, int]] = []
    triangle_sources: list[int] = []
    cursor = 0
    for face, count_value in enumerate(counts):
        count = int(count_value)
        for offset in range(1, count - 1):
            triangles.append(
                (
                    int(indices[cursor]),
                    int(indices[cursor + offset + 1]),
                    int(indices[cursor + offset]),
                )
            )
            triangle_corners.append((cursor, cursor + offset + 1, cursor + offset))
            triangle_sources.append(face)
        cursor += count
    if uv is None and normals is None:
        return trimesh.Trimesh(vertices=points, faces=np.asarray(triangles), process=False)

    expanded_vertices: list[np.ndarray] = []
    expanded_uv: list[np.ndarray] = []
    expanded_normals: list[np.ndarray] = []
    expanded_faces: list[tuple[int, int, int]] = []
    vertex_map: dict[tuple[object, ...], int] = {}
    corner_count = len(indices)
    for triangle, corners, source_face in zip(
        triangles, triangle_corners, triangle_sources, strict=True
    ):
        output_face: list[int] = []
        for vertex, corner in zip(triangle, corners, strict=True):
            uv_value = _scope_value(
                uv, vertex, source_face, corner, len(points), len(counts), corner_count
            )
            normal_value = _scope_value(
                normals, vertex, source_face, corner, len(points), len(counts), corner_count
            )
            key = (
                vertex,
                None if uv_value is None else tuple(float(v) for v in uv_value),
                None if normal_value is None else tuple(float(v) for v in normal_value),
            )
            output_index = vertex_map.get(key)
            if output_index is None:
                output_index = len(expanded_vertices)
                vertex_map[key] = output_index
                expanded_vertices.append(points[vertex])
                if uv is not None:
                    assert uv_value is not None
                    expanded_uv.append(uv_value)
                if normals is not None:
                    assert normal_value is not None
                    expanded_normals.append(normal_value)
            output_face.append(output_index)
        expanded_faces.append((output_face[0], output_face[1], output_face[2]))
    mesh = trimesh.Trimesh(
        vertices=np.asarray(expanded_vertices),
        faces=np.asarray(expanded_faces),
        process=False,
        vertex_normals=(np.asarray(expanded_normals, dtype=float) if expanded_normals else None),
    )
    if expanded_uv:
        mesh.visual = trimesh.visual.TextureVisuals(uv=np.asarray(expanded_uv, dtype=float))
    return mesh


def _axis_angle(axis: np.ndarray, angle_degrees: float) -> np.ndarray:
    length = float(np.linalg.norm(axis))
    if length == 0:
        return np.eye(4)
    x, y, z = axis / length
    angle = np.deg2rad(angle_degrees)
    cosine = float(np.cos(angle))
    sine = float(np.sin(angle))
    one_minus = 1.0 - cosine
    matrix = np.eye(4)
    matrix[:3, :3] = (
        (cosine + x * x * one_minus, x * y * one_minus - z * sine, x * z * one_minus + y * sine),
        (y * x * one_minus + z * sine, cosine + y * y * one_minus, y * z * one_minus - x * sine),
        (z * x * one_minus - y * sine, z * y * one_minus + x * sine, cosine + z * z * one_minus),
    )
    return matrix


def _xform_matrix(archive: _Archive, item: tuple[_Property, _Group]) -> tuple[np.ndarray, bool]:
    prop, group = item
    if prop.kind != 0:
        raise ValueError("Alembic .xform property is not compound")
    props = _property_map(archive, group)
    values_item = props.get(".vals")
    operations_item = props.get(".ops")
    inherits = True
    inherits_item = props.get(".inherits")
    if inherits_item is not None:
        inherits_values = archive.sample(inherits_item[1], inherits_item[0]).reshape(-1)
        if len(inherits_values):
            inherits = bool(inherits_values[0])
    if values_item is None and operations_item is None:
        return np.eye(4), inherits
    if values_item is None or operations_item is None:
        raise ValueError("Alembic Xform has only one of .vals and .ops")
    values = archive.sample(values_item[1], values_item[0]).reshape(-1).astype(float)
    operations = archive.sample(operations_item[1], operations_item[0]).reshape(-1).astype(np.uint8)
    matrix = np.eye(4)
    cursor = 0
    channel_counts = (3, 3, 4, 16, 1, 1, 1)
    for encoded in operations:
        operation = int(encoded) >> 4
        if operation >= len(channel_counts):
            raise ValueError(f"Alembic Xform has unknown operation {operation}")
        count = channel_counts[operation]
        if cursor + count > len(values):
            raise ValueError("Alembic Xform .vals is shorter than .ops declares")
        channels = values[cursor : cursor + count]
        cursor += count
        transform = np.eye(4)
        if operation == 0:
            transform[0, 0], transform[1, 1], transform[2, 2] = channels
        elif operation == 1:
            transform[:3, 3] = channels
        elif operation == 2:
            transform = _axis_angle(channels[:3], float(channels[3]))
        elif operation == 3:
            # Imath stores M44 values for row vectors; trimesh uses column vectors.
            transform = channels.reshape((4, 4)).T
        else:
            axis = np.zeros(3)
            axis[operation - 4] = 1.0
            transform = _axis_angle(axis, float(channels[0]))
        matrix = matrix @ transform
    if cursor != len(values):
        raise ValueError("Alembic Xform .vals has channels not described by .ops")
    return matrix, inherits


def _read_meshes(archive: _Archive) -> tuple[list[trimesh.Trimesh], int]:
    root = archive.group(archive.root.children[2])
    stack: list[tuple[_Group, _Object | None, int, np.ndarray]] = [(root, None, 0, np.eye(4))]
    meshes: list[trimesh.Trimesh] = []
    unsupported = 0
    visited = 0
    while stack:
        group, header, depth, parent_matrix = stack.pop()
        if depth > MAX_DEPTH:
            raise ValueError(f"Alembic objects nest deeper than {MAX_DEPTH} levels")
        visited += 1
        if visited > MAX_OBJECTS:
            raise ValueError("Alembic archive has too many objects")
        object_matrix = parent_matrix
        if header is not None:
            properties = (
                archive.group(group.children[0], depth + 1) if group.children else _Group(0, ())
            )
            top = _property_map(archive, properties)
            geom_item = top.get(".geom")
            schema = (header.metadata or {}).get("schema", "")
            if geom_item is not None and geom_item[0].kind == 0:
                schema = schema or (geom_item[0].metadata or {}).get("schema", "")
            if schema == "AbcGeom_PolyMesh_v1" and geom_item is not None:
                mesh = _mesh_from_geom(archive, geom_item[1])
                mesh.apply_transform(object_matrix)
                mesh.apply_transform(Y_UP_TO_Z_UP)
                meshes.append(mesh)
            elif schema == "AbcGeom_Xform_v3":
                xform_item = top.get(".xform")
                if xform_item is not None:
                    local, inherits = _xform_matrix(archive, xform_item)
                    object_matrix = (parent_matrix @ local) if inherits else local
            elif schema and schema != "AbcGeom_Xform_v3":
                unsupported += 1
        children = archive.object_headers(group)
        for index in range(len(children) - 1, -1, -1):
            group_index = index + 1
            if group_index >= len(group.children) or archive.is_data(group.children[group_index]):
                raise ValueError("Alembic object header has no matching object group")
            stack.append(
                (
                    archive.group(group.children[group_index], depth + 1),
                    children[index],
                    depth + 1,
                    object_matrix,
                )
            )
    return meshes, unsupported


def load_mesh(path: Path) -> trimesh.Trimesh:
    data = path.read_bytes()
    archive = _Archive(data)
    meshes, _ = _read_meshes(archive)
    meshes = [mesh for mesh in meshes if not mesh.is_empty]
    if not meshes:
        raise ValueError("Alembic archive has no static PolyMesh geometry")
    return (
        meshes[0] if len(meshes) == 1 else cast(trimesh.Trimesh, trimesh.util.concatenate(meshes))
    )


def parse_alembic_file(path: Path) -> ImportMetadata:
    archive = _Archive(path.read_bytes())
    meshes, unsupported = _read_meshes(archive)
    meshes = [mesh for mesh in meshes if not mesh.is_empty]
    warnings: list[Warning] = [
        warn(
            "units_assumed",
            Severity.info,
            "Alembic has no standard unit declaration; millimetres assumed",
        )
    ]
    if archive.animated:
        warnings.append(
            warn(
                "animation_ignored",
                Severity.warning,
                "Alembic animation is not imported; the first geometry sample was used",
            )
        )
    if unsupported:
        warnings.append(
            warn(
                "unsupported_geometry",
                Severity.warning,
                f"{unsupported} unsupported Alembic object(s) were left out",
                count=unsupported,
            )
        )
    if not meshes:
        return ImportMetadata(
            format="abc",
            representation="scene",
            unit_source="assumed",
            bbox=None,
            mesh=None,
            warnings=[*warnings, warn("empty_geometry", Severity.error, "no PolyMesh found")],
            parser=f"{PARSER} alembic-ogawa/1",
        )
    mesh = (
        meshes[0] if len(meshes) == 1 else cast(trimesh.Trimesh, trimesh.util.concatenate(meshes))
    )
    # UV seams intentionally duplicate vertices. Diagnostics are about physical topology,
    # so strip visuals before merge_vertices() decides whether seam vertices may coalesce.
    geometry = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
    stats, mesh_warnings = mesh_stats(geometry, scale=1.0)
    bbox = bbox_of(mesh, scale=1.0)
    return ImportMetadata(
        format="abc",
        representation="scene",
        unit_source="assumed",
        bbox=bbox,
        mesh=stats,
        warnings=[*warnings, *mesh_warnings, *extent_warnings(bbox)],
        file_metadata={"meshes": str(len(meshes)), "storage": "Ogawa"},
        parser=f"{PARSER} alembic-ogawa/1",
    )


# --- writer ---------------------------------------------------------------------------------


@dataclass(slots=True)
class _WData:
    payload: bytes


@dataclass(slots=True)
class _WGroup:
    children: list[_WData | _WGroup]


type _WNode = _WData | _WGroup


def _metadata_text(values: dict[str, str]) -> bytes:
    return ";".join(f"{key}={value}" for key, value in sorted(values.items())).encode()


def _property_header(
    name: str,
    kind: int,
    *,
    pod: int = 127,
    extent: int = 0,
    metadata: dict[str, str] | None = None,
) -> bytes:
    meta = _metadata_text(metadata or {})
    name_bytes = name.encode()
    max_size = max(len(name_bytes), len(meta), 1)
    hint = 0 if max_size <= 255 else 1 if max_size < 65536 else 2
    width = (1, 2, 4)[hint]
    meta_index = 0xFF if meta else 0
    info = hint << 2 | meta_index << 20
    body = bytearray()
    if kind:
        info |= kind | pod << 4 | extent << 12 | 0x400 | 0x800
    body += struct.pack("<I", info)
    if kind:
        body += (1).to_bytes(width, "little")  # exactly one, constant sample
    body += len(name_bytes).to_bytes(width, "little") + name_bytes
    if meta:
        body += len(meta).to_bytes(width, "little") + meta
    return bytes(body)


def _array_property(
    name: str,
    values: np.ndarray,
    pod: int,
    extent: int,
    metadata: dict[str, str],
) -> tuple[_WGroup, bytes]:
    dtype = _POD_DTYPES[pod]
    contiguous = np.ascontiguousarray(values, dtype=dtype).reshape((-1, extent))
    sample = _WData(b"\0" * 16 + contiguous.tobytes())
    return _WGroup([sample, _WData(b"")]), _property_header(
        name, 2, pod=pod, extent=extent, metadata=metadata
    )


def _object_header(name: str, metadata: dict[str, str]) -> bytes:
    encoded = name.encode()
    meta = _metadata_text(metadata)
    return struct.pack("<I", len(encoded)) + encoded + b"\xff" + struct.pack("<I", len(meta)) + meta


def _mesh_uv(mesh: trimesh.Trimesh) -> np.ndarray | None:
    uv = getattr(mesh.visual, "uv", None)
    if uv is None:
        return None
    values = np.asarray(uv, dtype=np.float32)
    return values if values.shape == (len(mesh.vertices), 2) else None


def write_alembic(mesh: trimesh.Trimesh, output_path: Path) -> None:
    """Write one static, Z-up PolyMesh. Coordinates are platform millimetres (Alembic itself
    has no units field); UVs and vertex normals are emitted as vertex-scope geom params."""
    alembic_mesh = mesh.copy()
    alembic_mesh.apply_transform(Z_UP_TO_Y_UP)
    vertices = np.asarray(alembic_mesh.vertices, dtype=np.float32)
    # Alembic's PolyMesh winding is opposite trimesh's triangle convention.
    faces = np.asarray(alembic_mesh.faces[:, ::-1], dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not len(faces):
        raise ValueError("cannot write an empty mesh to Alembic")
    if len(vertices) > MAX_VERTICES or len(faces) > MAX_TRIANGLES:
        raise ValueError("mesh is larger than the Alembic writer accepts")
    if not np.all(np.isfinite(vertices)):
        raise ValueError("cannot write non-finite vertices to Alembic")

    geom_children: list[_WNode] = []
    geom_headers = bytearray()
    bounds = np.concatenate((vertices.min(axis=0), vertices.max(axis=0))).astype("<f8")
    bounds_sample = _WGroup([_WData(b"\0" * 16 + bounds.tobytes())])
    geom_children.append(bounds_sample)
    geom_headers += _property_header(
        ".selfBnds", 1, pod=11, extent=6, metadata={"interpretation": "box"}
    )
    for name, values, pod, extent, metadata in (
        ("P", vertices, 10, 3, {"geoScope": "vtx", "interpretation": "point"}),
        (".faceIndices", faces.reshape(-1, 1), 6, 1, {}),
        (".faceCounts", np.full((len(faces), 1), 3, dtype=np.int32), 6, 1, {}),
    ):
        group, header = _array_property(name, values, pod, extent, metadata)
        geom_children.append(group)
        geom_headers += header
    uv = _mesh_uv(alembic_mesh)
    if uv is not None:
        group, header = _array_property(
            "uv",
            uv,
            10,
            2,
            {
                "arrayExtent": "1",
                "geoScope": "vtx",
                "interpretation": "vector",
                "isGeomParam": "true",
                "podExtent": "2",
                "podName": "float32_t",
            },
        )
        geom_children.append(group)
        geom_headers += header
    normals = np.asarray(alembic_mesh.vertex_normals, dtype=np.float32)
    if normals.shape == vertices.shape and np.all(np.isfinite(normals)):
        group, header = _array_property(
            "N",
            normals,
            10,
            3,
            {
                "arrayExtent": "1",
                "geoScope": "vtx",
                "interpretation": "normal",
                "isGeomParam": "true",
                "podExtent": "3",
                "podName": "float32_t",
            },
        )
        geom_children.append(group)
        geom_headers += header
    geom_children.append(_WData(bytes(geom_headers)))
    geom_group = _WGroup(geom_children)

    schema_meta = {
        "schema": "AbcGeom_PolyMesh_v1",
        "schemaBaseType": "AbcGeom_GeomBase_v1",
        "schemaObjTitle": "AbcGeom_PolyMesh_v1:.geom",
    }
    top_properties = _WGroup(
        [geom_group, _WData(_property_header(".geom", 0, metadata=schema_meta))]
    )
    mesh_object = _WGroup([top_properties, _WData(b"\0" * 32)])
    root_properties = _WGroup([])
    root_object = _WGroup(
        [
            root_properties,
            mesh_object,
            _WData(_object_header("mesh", schema_meta) + b"\0" * 32),
        ]
    )
    time_sampling = struct.pack("<IdId", 1, 1.0, 1, 0.0)
    archive_root = _WGroup(
        [
            _WData(struct.pack("<i", 0)),
            _WData(struct.pack("<i", 10808)),
            root_object,
            _WData(b"_ai_AlembicVersion=Alembic 1.8.8;_ai_Application=SOVA 3D"),
            _WData(time_sampling),
            _WData(b""),
        ]
    )
    output = bytearray(b"Ogawa\xff\x00\x01" + b"\0" * 8)

    def emit(node: _WNode) -> int:
        if isinstance(node, _WData):
            if not node.payload:
                return EMPTY_DATA
            address = len(output)
            output.extend(struct.pack("<Q", len(node.payload)))
            output.extend(node.payload)
            return address | DATA_BIT
        if not node.children:
            return 0
        references = [emit(child) for child in node.children]
        address = len(output)
        output.extend(struct.pack("<Q", len(references)))
        output.extend(struct.pack(f"<{len(references)}Q", *references))
        return address

    root_address = emit(archive_root)
    struct.pack_into("<Q", output, 8, root_address)
    output_path.write_bytes(output)
