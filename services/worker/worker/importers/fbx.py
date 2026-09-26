"""FBX import/export (F-014/F-015), without Autodesk's SDK.

FBX 7.x is a tree of named records, each with a list of typed values — binary (fixed-size
headers, arrays optionally zlib-compressed) or ASCII (`Name: values { ... }`). Both are read
into the same `_Node` tree here, and one scene builder turns `Objects`/`Connections` into a
single Z-up mesh: every Mesh geometry, under every Model that uses it, through the SDK's
full transform chain (translation, rotation offset/pivot, pre/post rotation with the
model's rotation order, scaling offset/pivot, and the geometric transform that is not
inherited). The file's `GlobalSettings` say which axis is up and how many centimetres a
unit is; both are honoured rather than guessed.

Hostile-input rules, in the spirit of the other container formats: nesting depth and
record counts are bounded, a compressed array must inflate to exactly the size its header
declares (never more — a zlib bomb stops at that length), and the total inflated size has
a budget. FBX 6.x and older (a different object model) are refused, not half-read.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from worker.importers.common import PARSER, bbox_of, extent_warnings, mesh_stats, warn
from worker.report import ImportMetadata, Severity, Warning

BINARY_MAGIC = b"Kaydara FBX Binary  \x00"
MAX_DEPTH = 64
MAX_RECORDS = 2_000_000
MAX_ARRAY_BYTES = 256 * 1024 * 1024
MAX_INFLATED_BYTES = 1024 * 1024 * 1024
MAX_TRIANGLES = 5_000_000
MIN_VERSION = 7000

Value = Any  # bool | int | float | str | bytes | np.ndarray


@dataclass(eq=False)
class _Node:
    name: str
    props: list[Value] = field(default_factory=list)
    kids: list[_Node] = field(default_factory=list)

    def child(self, name: str) -> _Node | None:
        return next((k for k in self.kids if k.name == name), None)

    def children(self, name: str) -> Iterator[_Node]:
        return (k for k in self.kids if k.name == name)

    def array(self, name: str) -> np.ndarray | None:
        node = self.child(name)
        if node is None or not node.props:
            return None
        value = node.props[0]
        if isinstance(value, np.ndarray):
            return value
        return np.asarray(node.props, dtype=float)


# --- binary ---------------------------------------------------------------------------------

_SCALARS = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}
_ARRAYS = {"f": np.float32, "d": np.float64, "l": np.int64, "i": np.int32, "b": np.bool_}


class _Binary:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.version = struct.unpack_from("<I", data, 23)[0]
        if self.version < MIN_VERSION:
            raise ValueError(f"FBX {self.version / 1000:.1f} is too old; export as FBX 2011+ (7.x)")
        self.wide = self.version >= 7500  # 64-bit record headers from FBX 2016 on
        self.records = 0
        self.inflated = 0

    def node(self, offset: int, depth: int) -> tuple[_Node | None, int]:
        if depth > MAX_DEPTH:
            raise ValueError(f"FBX records nest deeper than {MAX_DEPTH} levels")
        head = "<QQQB" if self.wide else "<IIIB"
        size = struct.calcsize(head)
        if offset + size > len(self.data):
            raise ValueError("the FBX file ends in the middle of a record")
        end, count, _, name_len = struct.unpack_from(head, self.data, offset)
        offset += size
        if end == 0:
            return None, offset  # the empty record that closes a list
        if not offset < end <= len(self.data):
            raise ValueError("an FBX record claims to end outside the file")
        self.records += 1
        if self.records > MAX_RECORDS:
            raise ValueError(f"the FBX file has more than {MAX_RECORDS} records")
        name = self.data[offset : offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        node = _Node(name)
        for _ in range(count):
            value, offset = self.value(offset)
            node.props.append(value)
        while offset < end:
            kid, offset = self.node(offset, depth + 1)
            if kid is None:
                break
            node.kids.append(kid)
        return node, end

    def value(self, offset: int) -> tuple[Value, int]:
        code = chr(self.data[offset])
        offset += 1
        if code in _SCALARS:
            fmt = _SCALARS[code]
            return struct.unpack_from(fmt, self.data, offset)[0], offset + struct.calcsize(fmt)
        if code in ("S", "R"):
            (length,) = struct.unpack_from("<I", self.data, offset)
            raw = self.data[offset + 4 : offset + 4 + length]
            if len(raw) != length:
                raise ValueError("an FBX string runs past the end of the file")
            text = raw.decode("utf-8", errors="replace") if code == "S" else raw
            return text, offset + 4 + length
        if code in _ARRAYS:
            count, encoding, stored = struct.unpack_from("<III", self.data, offset)
            offset += 12
            payload = self.data[offset : offset + stored]
            if len(payload) != stored:
                raise ValueError("an FBX array runs past the end of the file")
            dtype = np.dtype(_ARRAYS[code])
            expected = count * dtype.itemsize
            if expected > MAX_ARRAY_BYTES:
                raise ValueError("an FBX array is larger than the importer accepts")
            if encoding == 1:
                self.inflated += expected
                if self.inflated > MAX_INFLATED_BYTES:
                    raise ValueError("the FBX file inflates past the importer's budget")
                inflater = zlib.decompressobj()
                payload = inflater.decompress(payload, expected)
                if inflater.unconsumed_tail:
                    raise ValueError("an FBX array inflates to more than its header declares")
            elif encoding != 0:
                raise ValueError(f"unknown FBX array encoding {encoding}")
            if len(payload) != expected:
                raise ValueError("an FBX array's size does not match its header")
            return np.frombuffer(payload, dtype=dtype).copy(), offset + stored
        raise ValueError(f"unknown FBX property type {code!r}")


def _read_binary(data: bytes) -> tuple[list[_Node], int]:
    reader = _Binary(data)
    nodes: list[_Node] = []
    offset = 27
    while offset < len(data):
        node, offset = reader.node(offset, 0)
        if node is None:
            break
        nodes.append(node)
    return nodes, reader.version


# --- ASCII ----------------------------------------------------------------------------------

_ASCII_TOKEN = re.compile(
    r'[ \t\r]*(?:;[^\n]*|("(?:[^"\\]|\\.)*")|(\*\d+)|([{},])|([A-Za-z_][\w|]*[ \t]*:)'
    r"|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|([A-Za-z_]\w*)|(\n))",
)


def _ascii_tokens(text: str) -> Iterator[tuple[str, str]]:
    position = 0
    while position < len(text):
        match = _ASCII_TOKEN.match(text, position)
        if match is None or match.end() == position:
            if text[position].isspace():
                position += 1
                continue
            raise ValueError(f"unexpected character in the FBX file: {text[position]!r}")
        position = match.end()
        string, count, punct, key, number, word, newline = match.groups()
        if string is not None:
            yield "value", string[1:-1]
        elif count is not None:
            yield "count", count
        elif punct is not None:
            yield punct, punct
        elif key is not None:
            yield "key", key.rstrip(": \t")
        elif number is not None:
            yield "number", number
        elif word is not None:
            yield "value", word
        elif newline is not None:
            yield "newline", "\n"


def _read_ascii(text: str) -> tuple[list[_Node], int]:
    tokens = list(_ascii_tokens(text))
    version = 0
    header = re.search(r"FBX (\d+)\.(\d+)", text[:256])
    if header:
        version = int(header.group(1)) * 1000 + int(header.group(2)) * 100
    records = 0

    def block(i: int, depth: int) -> tuple[list[_Node], int]:
        nonlocal records
        if depth > MAX_DEPTH:
            raise ValueError(f"FBX records nest deeper than {MAX_DEPTH} levels")
        nodes: list[_Node] = []
        while i < len(tokens):
            kind, text_ = tokens[i]
            if kind == "}":
                return nodes, i + 1
            if kind in ("newline", ","):
                i += 1
                continue
            if kind != "key":
                raise ValueError(f"expected a record name in the FBX file, found {text_!r}")
            records += 1
            if records > MAX_RECORDS:
                raise ValueError(f"the FBX file has more than {MAX_RECORDS} records")
            node = _Node(text_)
            i += 1
            while i < len(tokens):
                kind, text_ = tokens[i]
                if kind == "number":
                    node.props.append(float(text_) if re.search(r"[.eE]", text_) else int(text_))
                elif kind == "value":
                    node.props.append(text_)
                elif kind == "count":
                    pass  # "*N": the next block's "a:" holds the N values
                elif kind == ",":
                    i += 1
                    while i < len(tokens) and tokens[i][0] == "newline":
                        i += 1  # a value list continues on the next line after a comma
                    continue
                else:
                    break
                i += 1
            if i < len(tokens) and tokens[i][0] == "{":
                node.kids, i = block(i + 1, depth + 1)
                values = node.child("a")
                if values is not None and not node.props:
                    node.props = [np.asarray(values.props, dtype=float)]
                    node.kids.remove(values)
            nodes.append(node)
        if depth:
            raise ValueError("an FBX block is never closed")
        return nodes, i

    nodes, _ = block(0, 0)
    return nodes, version


# --- scene ----------------------------------------------------------------------------------


def _properties(node: _Node) -> dict[str, list[Value]]:
    table = node.child("Properties70") or node.child("Properties60")
    if table is None:
        return {}
    return {str(p.props[0]): p.props[4:] for p in table.children("P") if len(p.props) >= 4}


def _vec(props: dict[str, list[Value]], name: str, default: tuple[float, float, float]) -> Any:
    values = props.get(name)
    if values is None or len(values) < 3:
        return np.asarray(default, dtype=float)
    return np.asarray([float(v) for v in values[:3]], dtype=float)


def _euler(degrees: np.ndarray, order: int = 0) -> np.ndarray:
    """FBX Euler angles; the order's letters are the order they are applied in."""
    rx, ry, rz = (
        trimesh.transformations.rotation_matrix(np.radians(a), axis)
        for a, axis in zip(degrees, np.eye(3), strict=True)
    )
    by_axis = {"X": rx, "Y": ry, "Z": rz}
    sequence = ("XYZ", "XZY", "YZX", "YXZ", "ZXY", "ZYX")[order if 0 <= order <= 5 else 0]
    matrix = np.eye(4)
    for axis in sequence:
        matrix = by_axis[axis] @ matrix
    return matrix


def _translate(vector: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = vector
    return matrix


def _local(props: dict[str, list[Value]]) -> np.ndarray:
    """T * Roff * Rp * Rpre * R * Rpost^-1 * Rp^-1 * Soff * Sp * S * Sp^-1 (the SDK's order)."""
    order_values = props.get("RotationOrder")
    order = int(order_values[0]) if order_values else 0
    pivot = _vec(props, "RotationPivot", (0, 0, 0))
    scale_pivot = _vec(props, "ScalingPivot", (0, 0, 0))
    return np.asarray(
        _translate(_vec(props, "Lcl Translation", (0, 0, 0)))
        @ _translate(_vec(props, "RotationOffset", (0, 0, 0)))
        @ _translate(pivot)
        @ _euler(_vec(props, "PreRotation", (0, 0, 0)))
        @ _euler(_vec(props, "Lcl Rotation", (0, 0, 0)), order)
        @ np.linalg.inv(_euler(_vec(props, "PostRotation", (0, 0, 0))))
        @ _translate(-pivot)
        @ _translate(_vec(props, "ScalingOffset", (0, 0, 0)))
        @ _translate(scale_pivot)
        @ np.diag([*_vec(props, "Lcl Scaling", (1, 1, 1)), 1.0])
        @ _translate(-scale_pivot)
    )


def _geometric(props: dict[str, list[Value]]) -> np.ndarray:
    return np.asarray(
        _translate(_vec(props, "GeometricTranslation", (0, 0, 0)))
        @ _euler(_vec(props, "GeometricRotation", (0, 0, 0)))
        @ np.diag([*_vec(props, "GeometricScaling", (1, 1, 1)), 1.0])
    )


def _axes(settings: dict[str, list[Value]]) -> np.ndarray:
    """File axes -> the platform's Z-up, right-handed (up -> +Z, the right axis -> +X)."""

    def axis(name: str, sign: str, default: int) -> np.ndarray:
        index = int((settings.get(name) or [default])[0])
        direction = int((settings.get(sign) or [1])[0])
        if index not in (0, 1, 2):
            raise ValueError(f"GlobalSettings.{name} is not an axis")
        unit: np.ndarray = np.eye(3)[index]
        return unit if direction >= 0 else -unit

    up = axis("UpAxis", "UpAxisSign", 1)
    right = axis("CoordAxis", "CoordAxisSign", 0)
    if abs(float(np.dot(up, right))) > 0.5:
        raise ValueError("GlobalSettings names the same axis as up and right")
    matrix = np.eye(4)
    matrix[:3, :3] = np.vstack([right, np.cross(up, right), up])
    return matrix


def _mesh_of(geometry: _Node) -> tuple[np.ndarray, np.ndarray]:
    vertices = geometry.array("Vertices")
    index = geometry.array("PolygonVertexIndex")
    if vertices is None or index is None:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    if vertices.size % 3:
        raise ValueError("an FBX mesh's Vertices are not x y z triples")
    points = np.asarray(vertices, dtype=float).reshape(-1, 3)
    corners = np.asarray(index, dtype=np.int64)
    ends = corners < 0
    corners = np.where(ends, -corners - 1, corners)  # a negative index closes its polygon
    if corners.size and (corners.max() >= len(points) or corners.min() < 0):
        raise ValueError("an FBX polygon index points past the end of the vertices")
    faces: list[np.ndarray] = []
    start = 0
    for stop in np.flatnonzero(ends).tolist():
        polygon = corners[start : stop + 1]
        start = stop + 1
        if len(polygon) >= 3:  # a fan from the first corner, like every Web3D polygon too
            faces.append(np.c_[np.full(len(polygon) - 2, polygon[0]), polygon[1:-1], polygon[2:]])
        if sum(len(f) for f in faces) > MAX_TRIANGLES:
            raise ValueError(f"the FBX file has more than {MAX_TRIANGLES} triangles")
    return points, np.vstack(faces) if faces else np.zeros((0, 3), dtype=np.int64)


def _scene(nodes: list[_Node]) -> tuple[trimesh.Trimesh, float, dict[str, int]]:
    """One Z-up mesh in the file's units, centimetres per unit, and what was left out."""
    top = {node.name: node for node in nodes}
    settings = _properties(top["GlobalSettings"]) if "GlobalSettings" in top else {}
    unit_cm = float((settings.get("UnitScaleFactor") or [1.0])[0])
    if not unit_cm > 0:
        raise ValueError("GlobalSettings.UnitScaleFactor must be positive")
    objects = top.get("Objects")
    if objects is None:
        raise ValueError("the FBX file has no Objects")

    geometries: dict[int, _Node] = {}
    models: dict[int, _Node] = {}
    skipped: dict[str, int] = {}
    for obj in objects.kids:
        if not obj.props or not isinstance(obj.props[0], (int, np.integer)):
            continue
        kind = str(obj.props[2]) if len(obj.props) > 2 else ""
        if obj.name == "Geometry":
            if kind == "Mesh":
                geometries[int(obj.props[0])] = obj
            elif kind != "Shape":  # blend shapes deform a mesh; they are not geometry
                skipped[kind or "Geometry"] = skipped.get(kind or "Geometry", 0) + 1
        elif obj.name == "Model":
            models[int(obj.props[0])] = obj

    parent: dict[int, int] = {}
    geometry_owner: list[tuple[int, int]] = []
    connections = top.get("Connections")
    for link in connections.children("C") if connections else ():
        if len(link.props) < 3 or link.props[0] != "OO":
            continue
        child, owner = int(link.props[1]), int(link.props[2])
        if child in geometries and owner in models:
            geometry_owner.append((child, owner))
        elif child in models:
            parent[child] = owner

    world: dict[int, np.ndarray] = {}

    def placed(model_id: int, depth: int = 0) -> np.ndarray:
        if depth > MAX_DEPTH:
            raise ValueError("FBX models are parented deeper than the importer allows (or loop)")
        if model_id not in world:
            above = parent.get(model_id)
            base = placed(above, depth + 1) if above in models else np.eye(4)
            world[model_id] = base @ _local(_properties(models[model_id]))
        return world[model_id]

    to_z_up = _axes(settings)
    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    offset = triangles = 0
    built: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for geometry_id, model_id in geometry_owner:
        if geometry_id not in built:
            built[geometry_id] = _mesh_of(geometries[geometry_id])
        points, tris = built[geometry_id]
        triangles += len(tris)
        if triangles > MAX_TRIANGLES:
            raise ValueError(f"the FBX scene has more than {MAX_TRIANGLES} triangles")
        if not len(tris):
            continue
        props = _properties(models[model_id])
        matrix = to_z_up @ placed(model_id) @ _geometric(props)
        homogeneous = np.c_[points, np.ones(len(points))]
        vertices.append((matrix @ homogeneous.T).T[:, :3])
        if np.linalg.det(matrix[:3, :3]) < 0:
            tris = tris[:, ::-1]  # a mirroring transform turns faces inside out
        faces.append(tris + offset)
        offset += len(points)
    orphans = len(geometries) - len({g for g, _ in geometry_owner})
    if orphans > 0:
        skipped["unplaced Mesh"] = orphans
    if not faces:
        return trimesh.Trimesh(), unit_cm, skipped
    mesh = trimesh.Trimesh(vertices=np.vstack(vertices), faces=np.vstack(faces), process=False)
    return mesh, unit_cm, skipped


def _read(data: bytes) -> tuple[list[_Node], int]:
    if data.startswith(BINARY_MAGIC):
        return _read_binary(data)
    text = data.decode("utf-8", errors="replace")
    if not re.search(r"^\s*(?:;.*\n\s*)*FBXHeaderExtension\s*:", text[:4096], re.MULTILINE):
        raise ValueError("not an FBX file (neither the binary header nor an ASCII FBX header)")
    nodes, version = _read_ascii(text)
    if version and version < MIN_VERSION:
        raise ValueError(f"FBX {version / 1000:.1f} is too old; export as FBX 2011+ (7.x)")
    return nodes, version


def load_mesh(path: Path) -> tuple[trimesh.Trimesh, float]:
    """The scene as one Z-up mesh and its scale to millimetres."""
    nodes, _ = _read(path.read_bytes())
    mesh, unit_cm, _ = _scene(nodes)
    return mesh, unit_cm * 10.0


def parse_fbx_file(path: Path) -> ImportMetadata:
    nodes, version = _read(path.read_bytes())
    mesh, unit_cm, skipped = _scene(nodes)
    scale = unit_cm * 10.0
    source_units = f"{unit_cm:g} * centimeter"
    warnings: list[Warning] = [
        warn(
            "unsupported_geometry",
            Severity.warning,
            f"{count} {kind} object(s) were left out",
            node=kind,
            count=count,
        )
        for kind, count in sorted(skipped.items())
    ]
    if mesh.is_empty:
        return ImportMetadata(
            format="fbx",
            representation="scene",
            unit_source="file",
            source_units=source_units,
            scale_to_mm=scale,
            bbox=None,
            mesh=None,
            warnings=[*warnings, warn("empty_geometry", Severity.error, "no mesh geometry found")],
            parser=f"{PARSER} fbx/{version}",
        )
    stats, mesh_warnings = mesh_stats(mesh, scale=scale)
    bbox = bbox_of(mesh, scale=scale)
    warnings.extend(mesh_warnings)
    warnings.extend(extent_warnings(bbox))
    return ImportMetadata(
        format="fbx",
        representation="scene",
        unit_source="file",
        source_units=source_units,
        scale_to_mm=scale,
        bbox=bbox,
        mesh=stats,
        warnings=warnings,
        parser=f"{PARSER} fbx/{version}",
    )


# --- export (binary FBX 7.4) ----------------------------------------------------------------


def _pack_value(value: Value) -> bytes:
    if isinstance(value, bool):
        return b"C" + struct.pack("<?", value)
    if isinstance(value, np.int64):  # object ids are 64-bit
        return b"L" + struct.pack("<q", int(value))
    if isinstance(value, int):
        return b"I" + struct.pack("<i", value)
    if isinstance(value, float):
        return b"D" + struct.pack("<d", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"S" + struct.pack("<I", len(raw)) + raw
    if isinstance(value, bytes):
        return b"S" + struct.pack("<I", len(value)) + value
    if isinstance(value, np.ndarray):
        code = {np.dtype(np.float64): b"d", np.dtype(np.int32): b"i", np.dtype(np.int64): b"l"}[
            value.dtype
        ]
        raw = zlib.compress(np.ascontiguousarray(value).tobytes())
        return code + struct.pack("<III", len(value), 1, len(raw)) + raw
    raise TypeError(f"cannot write {type(value).__name__} to FBX")


def _pack_node(node: _Node, offset: int) -> bytes:
    name = node.name.encode("utf-8")
    props = b"".join(_pack_value(v) for v in node.props)
    start = offset + 13 + len(name) + len(props)
    body = b""
    for kid in node.kids:
        body += _pack_node(kid, start + len(body))
    if node.kids or not node.props:
        body += b"\x00" * 13
    end = start + len(body)
    return struct.pack("<IIIB", end, len(node.props), len(props), len(name)) + name + props + body


def _p(name: str, kind: str, *values: Value) -> _Node:
    return _Node("P", [name, kind, "", "", *values])


def write_fbx(mesh: trimesh.Trimesh, output_path: Path) -> None:
    """Y-up (FBX's own default) and millimetres, stated in GlobalSettings, one Mesh model."""
    vertices = np.asarray(mesh.vertices, dtype=float) @ np.array(
        [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]
    )  # Z-up (x, y, z) -> Y-up (x, z, -y)
    faces = np.asarray(mesh.faces, dtype=np.int64).copy()
    faces[:, 2] = -faces[:, 2] - 1  # the last corner of each polygon is stored negated
    geometry_id, model_id = np.int64(1_000_001), np.int64(1_000_002)
    settings = _Node(
        "Properties70",
        kids=[
            _p("UpAxis", "int", 1),
            _p("UpAxisSign", "int", 1),
            _p("FrontAxis", "int", 2),
            _p("FrontAxisSign", "int", 1),
            _p("CoordAxis", "int", 0),
            _p("CoordAxisSign", "int", 1),
            _p("UnitScaleFactor", "double", 0.1),
            _p("OriginalUnitScaleFactor", "double", 0.1),
        ],
    )
    nodes = [
        _Node(
            "FBXHeaderExtension",
            kids=[
                _Node("FBXHeaderVersion", [1003]),
                _Node("FBXVersion", [7400]),
                _Node("Creator", ["Physical AI 3D"]),
            ],
        ),
        _Node("GlobalSettings", kids=[_Node("Version", [1000]), settings]),
        _Node(
            "Objects",
            kids=[
                _Node(
                    "Geometry",
                    [geometry_id, "Body\x00\x01Geometry", "Mesh"],
                    [
                        _Node("Vertices", [np.ascontiguousarray(vertices.ravel())]),
                        _Node("PolygonVertexIndex", [faces.ravel().astype(np.int32)]),
                        _Node("GeometryVersion", [124]),
                    ],
                ),
                _Node(
                    "Model",
                    [model_id, "Body\x00\x01Model", "Mesh"],
                    [_Node("Version", [232]), _Node("Properties70")],
                ),
            ],
        ),
        _Node(
            "Connections",
            kids=[
                _Node("C", ["OO", geometry_id, model_id]),
                _Node("C", ["OO", model_id, np.int64(0)]),
            ],
        ),
    ]
    out = bytearray(BINARY_MAGIC + b"\x1a\x00" + struct.pack("<I", 7400))
    for node in nodes:
        out += _pack_node(node, len(out))
    out += b"\x00" * 13
    output_path.write_bytes(bytes(out))
