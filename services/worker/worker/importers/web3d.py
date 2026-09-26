"""X3D (XML and ClassicVRML encodings) and VRML97 import/export (F-014/F-015).

All three are Web3D scene graphs with one model: Transform/Group nodes over Shapes whose
geometry is an IndexedFaceSet (or a Box/Sphere/Cylinder/Cone primitive, an ElevationGrid
or an Extrusion), Y-up, in metres unless an X3D file says otherwise with a UNIT statement.
One walker (`_collect`) flattens any of them into a single Z-up mesh in the file's own
units — the platform's single-body convention, same as DAE/USDZ — and the frontends differ
only in how they read bytes into nodes (.x3dv is VRML97 syntax with X3D's header and
statements, so it shares the VRML reader).

Hostile-input rules, in the spirit of 3MF/USDZ: an X3D DOCTYPE may name the public DTD but
never carry an internal subset (the only place a document can declare entities); `Inline`
and other external references are never fetched; PROTO is refused rather than interpreted;
and DEF/USE — a scene graph's own amplification vector (a DEF reused ten times inside a
DEF reused ten times...) — is bounded by nesting depth and a total triangle budget.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
import trimesh
from lxml import etree

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

MAX_DEPTH = 64
# The same order as the largest mesh files the platform accepts (a 200 MB binary STL is
# ~4M triangles), and small enough for the sandbox's memory limit once expanded.
MAX_TRIANGLES = 5_000_000
MAX_VISITS = 1_000_000
PRIMITIVE_SECTIONS = 48
# Past this the file is more likely millimetres written under a metres-only spec (common
# with CAD exporters) than a genuine 50-metre object.
SUSPICIOUS_METRES = 50.0

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


@dataclass(eq=False)
class _Node:
    type: str
    fields: dict[str, list[float] | str] = field(default_factory=dict)
    kids: list[_Node] = field(default_factory=list)

    def floats(self, name: str) -> list[float] | None:
        value = self.fields.get(name)
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return [float(token) for token in _NUMBER.findall(value)]

    def vec(self, name: str, default: list[float]) -> list[float]:
        value = self.floats(name)
        if value is None:
            return default
        if len(value) != len(default):
            raise ValueError(f"{self.type}.{name} needs {len(default)} numbers, has {len(value)}")
        return value

    def flag(self, name: str, default: bool) -> bool:
        value = self.fields.get(name)
        return value.strip().lower() == "true" if isinstance(value, str) else default


# --- geometry -------------------------------------------------------------------------------


def _points(node: _Node) -> np.ndarray:
    coord = next((k for k in node.kids if k.type in ("Coordinate", "CoordinateDouble")), None)
    if coord is None:
        raise ValueError(f"{node.type} has no Coordinate")
    flat = coord.floats("point") or []
    if len(flat) % 3:
        raise ValueError("Coordinate.point is not a list of x y z triples")
    return np.asarray(flat, dtype=float).reshape(-1, 3)


def _indices(values: list[float] | None, count: int) -> np.ndarray:
    if not values:
        return np.zeros(0, dtype=np.int64)
    index = np.asarray(values, dtype=float)
    if not np.all(index == np.round(index)):
        raise ValueError("coordinate indices must be integers")
    index = index.astype(np.int64)
    used = index[index >= 0]
    if used.size and int(used.max()) >= count:
        raise ValueError("an index points past the end of the Coordinate list")
    return index


def _oriented(node: _Node, faces: np.ndarray) -> np.ndarray:
    return faces if node.flag("ccw", True) else faces[:, ::-1]


def _indexed_face_set(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    points = _points(node)
    index = _indices(node.floats("coordIndex"), len(points))
    faces: list[tuple[int, int, int]] = []
    polygon: list[int] = []
    for value in [*index.tolist(), -1]:
        if value < -1:
            raise ValueError("coordIndex has a negative index other than the -1 separator")
        if value >= 0:
            polygon.append(value)
            continue
        # a polygon is a fan from its first corner; fewer than three corners is no face
        faces.extend((polygon[0], polygon[i], polygon[i + 1]) for i in range(1, len(polygon) - 1))
        polygon = []
    return points, _oriented(node, np.asarray(faces, dtype=np.int64).reshape(-1, 3))


def _indexed_triangle_set(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    points = _points(node)
    index = _indices(node.floats("index"), len(points))
    if index.size % 3 or (index < 0).any():
        raise ValueError("IndexedTriangleSet.index must be whole triangles")
    return points, _oriented(node, index.reshape(-1, 3))


def _triangle_set(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    points = _points(node)
    usable = len(points) - len(points) % 3
    return points, _oriented(node, np.arange(usable, dtype=np.int64).reshape(-1, 3))


def _y_axis(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """trimesh builds round primitives along Z; Web3D's run along Y."""
    lo, hi = mesh.bounds[0][2], mesh.bounds[1][2]
    mesh.apply_translation((0.0, 0.0, -(lo + hi) / 2.0))
    mesh.apply_transform(Z_UP_TO_Y_UP)
    return np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces, dtype=np.int64)


def _box(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    mesh = trimesh.creation.box(extents=node.vec("size", [2.0, 2.0, 2.0]))
    return np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces, dtype=np.int64)


def _sphere(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    (radius,) = node.vec("radius", [1.0])
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    return np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces, dtype=np.int64)


def _cylinder(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    (radius,) = node.vec("radius", [1.0])
    (height,) = node.vec("height", [2.0])
    return _y_axis(trimesh.creation.cylinder(radius, height, sections=PRIMITIVE_SECTIONS))


def _cone(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    (radius,) = node.vec("bottomRadius", [1.0])
    (height,) = node.vec("height", [2.0])
    return _y_axis(trimesh.creation.cone(radius, height, sections=PRIMITIVE_SECTIONS))


def _elevation_grid(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    """A height field over the XZ plane: x along +X, z along +Z, heights along +Y."""
    (x_dim,) = node.vec("xDimension", [0.0])
    (z_dim,) = node.vec("zDimension", [0.0])
    (x_spacing,) = node.vec("xSpacing", [1.0])
    (z_spacing,) = node.vec("zSpacing", [1.0])
    nx, nz = int(x_dim), int(z_dim)
    heights = node.floats("height") or []
    if nx != x_dim or nz != z_dim or nx < 2 or nz < 2:
        raise ValueError("ElevationGrid needs whole xDimension and zDimension of at least 2")
    if len(heights) != nx * nz:
        raise ValueError(f"ElevationGrid has {len(heights)} heights for a {nx}x{nz} grid")
    xs, zs = np.meshgrid(np.arange(nx) * x_spacing, np.arange(nz) * z_spacing)
    points = np.c_[xs.ravel(), np.asarray(heights, dtype=float), zs.ravel()]
    i, j = np.meshgrid(np.arange(nx - 1), np.arange(nz - 1))
    a = (j * nx + i).ravel()
    # corner, its +z neighbour, its +x neighbour: counter-clockwise seen from +Y, top up
    faces = np.r_[np.c_[a, a + nx, a + 1], np.c_[a + 1, a + nx, a + nx + 1]]
    return points, _oriented(node, faces)


def _spine_frames(spine: np.ndarray) -> list[np.ndarray]:
    """Each spine point's cross-section plane as columns X, Y, Z (the X3D Extrusion rules)."""
    n = len(spine)
    closed = bool(np.allclose(spine[0], spine[-1]))
    ys: list[np.ndarray | None] = []
    zs: list[np.ndarray | None] = []
    for i in range(n):
        z: np.ndarray | None
        if closed and i in (0, n - 1):
            y = spine[1] - spine[n - 2]
            z = np.cross(spine[1] - spine[0], spine[n - 2] - spine[0])
        elif i == 0:
            y, z = spine[1] - spine[0], None
        elif i == n - 1:
            y, z = spine[n - 1] - spine[n - 2], None
        else:
            y = spine[i + 1] - spine[i - 1]
            z = np.cross(spine[i + 1] - spine[i], spine[i - 1] - spine[i])
        ys.append(y if np.linalg.norm(y) > 1e-12 else None)
        zs.append(z if z is not None and np.linalg.norm(z) > 1e-12 else None)
    if all(y is None for y in ys):
        raise ValueError("the Extrusion spine has no length")
    if all(z is None for z in zs):  # a straight spine: turn +Y onto it, carry X and Z along
        direction = next(y for y in ys if y is not None)
        turn = np.asarray(trimesh.geometry.align_vectors([0.0, 1.0, 0.0], direction))[:3, :3]
        return [turn for _ in range(n)]
    # an open spine's ends (and any straight stretch) take the nearest turn's plane
    first_y = next(y for y in ys if y is not None)
    first_z = next(z for z in zs if z is not None)
    frames: list[np.ndarray] = []
    for y_raw, z_raw in zip(ys, zs, strict=True):
        y = (frames[-1][:, 1] if frames else first_y) if y_raw is None else y_raw
        z = (frames[-1][:, 2] if frames else first_z) if z_raw is None else z_raw
        if frames and float(np.dot(z, frames[-1][:, 2])) < 0:
            z = -z  # keep the plane from flipping where the spine changes its turn
        y = y / np.linalg.norm(y)
        z = z / np.linalg.norm(z)
        x = np.cross(y, z)
        frames.append(np.c_[x / np.linalg.norm(x), y, z])
    return frames


def _per_spine(values: list[float] | None, width: int, default: list[float], n: int) -> np.ndarray:
    rows: np.ndarray = np.asarray(values or default, dtype=float)
    if rows.size % width:
        raise ValueError(f"Extrusion values come in groups of {width}")
    rows = rows.reshape(-1, width)
    if len(rows) == 1:
        return np.repeat(rows, n, axis=0)
    if len(rows) != n:
        raise ValueError("Extrusion scale/orientation needs one value, or one per spine point")
    return rows


def _cap(section: np.ndarray) -> np.ndarray:
    """Triangles over a closed cross-section, as indices into it (concave shapes too)."""
    polygon = shapely.Polygon(section)
    if not polygon.is_valid or polygon.area <= 0:
        return np.zeros((0, 3), dtype=np.int64)
    lookup = {(float(x), float(z)): k for k, (x, z) in enumerate(section)}
    triangles = [
        [lookup[(float(x), float(z))] for x, z in shapely.get_coordinates(triangle)[:3]]
        for triangle in shapely.constrained_delaunay_triangles(polygon).geoms
    ]
    return np.asarray(triangles, dtype=np.int64).reshape(-1, 3)


def _facing(points: np.ndarray, faces: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """The same triangles, each wound so its normal points along `direction`."""
    if not len(faces):
        return faces
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    backwards = np.einsum("ij,j->i", np.cross(b - a, c - a), direction) < 0
    faces = faces.copy()
    faces[backwards] = faces[backwards][:, ::-1]
    return faces


def _extrusion(node: _Node) -> tuple[np.ndarray, np.ndarray]:
    """A cross-section swept along a spine, scaled and turned at every spine point."""
    cross: np.ndarray = np.asarray(
        node.floats("crossSection") or [1, 1, 1, -1, -1, -1, -1, 1, 1, 1], dtype=float
    )
    spine: np.ndarray = np.asarray(node.floats("spine") or [0, 0, 0, 0, 1, 0], dtype=float)
    if cross.size % 2 or spine.size % 3:
        raise ValueError("Extrusion crossSection is (x z) pairs and spine is (x y z) triples")
    cross, spine = cross.reshape(-1, 2), spine.reshape(-1, 3)
    n, m = len(spine), len(cross)
    if n < 2 or m < 2:
        raise ValueError("an Extrusion needs two spine points and two cross-section points")
    scale = _per_spine(node.floats("scale"), 2, [1.0, 1.0], n)
    orientation = _per_spine(node.floats("orientation"), 4, [0.0, 0.0, 1.0, 0.0], n)
    frames = _spine_frames(spine)
    rings = []
    for i in range(n):
        local = np.c_[cross[:, 0] * scale[i, 0], np.zeros(m), cross[:, 1] * scale[i, 1]]
        local = local @ _rotation(list(orientation[i]))[:3, :3].T
        rings.append(spine[i] + local @ frames[i].T)
    points = np.vstack(rings)

    ring, corner = np.meshgrid(np.arange(n - 1), np.arange(m - 1), indexing="ij")
    a = (ring * m + corner).ravel()
    sides = np.r_[np.c_[a, a + 1, a + m + 1], np.c_[a, a + m + 1, a + m]]
    closed_section = bool(np.allclose(cross[0], cross[-1]))
    outline = cross[:-1] if closed_section else cross
    # the sides above face outward when the section runs clockwise in (x, z)
    signed = float(np.sum(outline[:, 0] * np.roll(outline[:, 1], -1)))
    signed -= float(np.sum(np.roll(outline[:, 0], -1) * outline[:, 1]))
    if signed > 0:
        sides = sides[:, ::-1]
    faces = [sides]
    if closed_section and not np.allclose(spine[0], spine[-1]) and len(outline) >= 3:
        cap = _cap(outline)
        if node.flag("beginCap", True):
            faces.append(_facing(points, cap, -frames[0][:, 1]))
        if node.flag("endCap", True):
            faces.append(_facing(points, cap + (n - 1) * m, frames[-1][:, 1]))
    return points, np.vstack(faces)


_GEOMETRY: dict[str, Callable[[_Node], tuple[np.ndarray, np.ndarray]]] = {
    "IndexedFaceSet": _indexed_face_set,
    "IndexedTriangleSet": _indexed_triangle_set,
    "TriangleSet": _triangle_set,
    "Box": _box,
    "Sphere": _sphere,
    "Cylinder": _cylinder,
    "Cone": _cone,
    "ElevationGrid": _elevation_grid,
    "Extrusion": _extrusion,
}
_GROUPS = frozenset({"Scene", "Group", "StaticGroup", "Collision", "Anchor", "Billboard"})
# Geometry this importer does not tessellate; reported rather than silently dropped.
_UNSUPPORTED_GEOMETRY = frozenset(
    {"Text", "NurbsPatchSurface", "NurbsTrimmedSurface", "GeoElevationGrid", "PointSet"}
)


# --- the walker -----------------------------------------------------------------------------


def _rotation(values: list[float]) -> np.ndarray:
    axis = np.asarray(values[:3], dtype=float)
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12 or values[3] == 0.0:
        return np.eye(4)
    return np.asarray(trimesh.transformations.rotation_matrix(values[3], axis / norm))


def _transform(node: _Node) -> np.ndarray:
    """T x C x R x SR x S x -SR x -C, as the X3D/VRML Transform node defines it."""
    translate = np.eye(4)
    translate[:3, 3] = node.vec("translation", [0.0, 0.0, 0.0])
    centre = np.eye(4)
    centre[:3, 3] = node.vec("center", [0.0, 0.0, 0.0])
    uncentre = np.eye(4)
    uncentre[:3, 3] = -centre[:3, 3]
    rotate = _rotation(node.vec("rotation", [0.0, 0.0, 1.0, 0.0]))
    orient = _rotation(node.vec("scaleOrientation", [0.0, 0.0, 1.0, 0.0]))
    scale = np.diag([*node.vec("scale", [1.0, 1.0, 1.0]), 1.0])
    return np.asarray(translate @ centre @ rotate @ orient @ scale @ orient.T @ uncentre)


def _descend(node: _Node) -> list[_Node]:
    """The children a grouping node actually renders; nothing for any other node."""
    if node.type in _GROUPS or node.type == "Transform":
        return node.kids
    if node.type == "Switch":
        (choice,) = node.vec("whichChoice", [-1.0])
        return [node.kids[int(choice)]] if 0 <= int(choice) < len(node.kids) else []
    if node.type == "LOD":
        return node.kids[:1]  # the first level is the most detailed
    return []


@dataclass
class _Collected:
    vertices: list[np.ndarray] = field(default_factory=list)
    faces: list[np.ndarray] = field(default_factory=list)
    offset: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    # A DEF'd geometry reused by many USEs is tessellated once, not once per use.
    built: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)

    def geometry(self, node: _Node) -> tuple[np.ndarray, np.ndarray]:
        if id(node) not in self.built:
            self.built[id(node)] = _GEOMETRY[node.type](node)
        return self.built[id(node)]

    def add(self, points: np.ndarray, faces: np.ndarray, matrix: np.ndarray) -> None:
        if not len(faces):
            return
        homogeneous = np.c_[points, np.ones(len(points))]
        self.vertices.append((matrix @ homogeneous.T).T[:, :3])
        self.faces.append(faces + self.offset)
        self.offset += len(points)

    def skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1


def _expanded(
    node: _Node, depth: int, memo: dict[int, tuple[int, int]], out: _Collected
) -> tuple[int, int]:
    """(triangles, node visits) the scene expands to, counted once per distinct node.

    DEF/USE makes the scene a DAG that can be exponentially larger than the file; memoizing
    by node counts that in linear time, so an amplification bomb is refused before a single
    vertex array is allocated. A node met again while still being counted is a USE cycle:
    it counts as nothing here, and the walker's depth limit refuses it.
    """
    if depth > MAX_DEPTH:
        raise ValueError(f"the scene graph nests deeper than {MAX_DEPTH} levels (or USEs itself)")
    if id(node) in memo:
        return memo[id(node)]
    memo[id(node)] = (0, 0)
    triangles, visits = 0, 1
    if node.type == "Shape":
        triangles = sum(len(out.geometry(k)[1]) for k in node.kids if k.type in _GEOMETRY)
    for kid in _descend(node):
        kid_triangles, kid_visits = _expanded(kid, depth + 1, memo, out)
        triangles += kid_triangles
        visits += kid_visits
        if triangles > MAX_TRIANGLES or visits > MAX_VISITS:
            raise ValueError(
                f"the scene expands past {MAX_TRIANGLES} triangles or {MAX_VISITS} nodes "
                "(DEF/USE amplification or an oversized model)"
            )
    memo[id(node)] = (triangles, visits)
    return triangles, visits


def _walk(node: _Node, matrix: np.ndarray, depth: int, out: _Collected) -> None:
    if depth > MAX_DEPTH:
        raise ValueError(f"the scene graph nests deeper than {MAX_DEPTH} levels (or USEs itself)")
    if node.type == "Transform":
        matrix = matrix @ _transform(node)
    elif node.type == "Shape":
        for kid in node.kids:
            if kid.type in _GEOMETRY:
                out.add(*out.geometry(kid), matrix)
            elif kid.type in _UNSUPPORTED_GEOMETRY:
                out.skip(kid.type)
        return
    elif node.type == "Inline":
        out.skip("Inline")  # an external file; never fetched
        return
    # lights, viewpoints, sensors, appearance: _descend gives them no children to mesh
    for kid in _descend(node):
        _walk(kid, matrix, depth + 1, out)


def _collect(root: _Node) -> tuple[trimesh.Trimesh, dict[str, int]]:
    out = _Collected()
    triangles, visits = _expanded(root, 0, {}, out)
    if triangles > MAX_TRIANGLES or visits > MAX_VISITS:
        raise ValueError(
            f"the scene expands past {MAX_TRIANGLES} triangles or {MAX_VISITS} nodes "
            "(DEF/USE amplification or an oversized model)"
        )
    _walk(root, Y_UP_TO_Z_UP, 0, out)
    if not out.faces:
        return trimesh.Trimesh(), out.skipped
    vertices = np.vstack(out.vertices)
    faces = np.vstack(out.faces)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False), out.skipped


# --- X3D (XML encoding) ---------------------------------------------------------------------

_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    huge_tree=False,
    remove_comments=True,
    remove_pis=True,
)
_DOCTYPE = re.compile(rb"<!DOCTYPE[^>\[]*(\[)?", re.IGNORECASE)


def _read_x3d(data: bytes) -> tuple[_Node, float | None]:
    """The scene and the metres-per-unit of an X3D UNIT statement, if the file has one."""
    doctype = _DOCTYPE.search(data[:65536])
    if doctype and doctype.group(1):
        raise ValueError("the X3D DOCTYPE carries an internal subset (entity declarations)")
    root = etree.fromstring(data, _XML_PARSER)
    if etree.QName(root).localname != "X3D":
        raise ValueError("not an X3D document")

    metres_per_unit: float | None = None
    scene: _Node | None = None
    defs: dict[str, _Node] = {}

    def convert(element: etree._Element) -> _Node:
        use = element.get("USE")
        if use is not None:
            if use not in defs:
                raise ValueError(f"USE {use!r} comes before its DEF")
            return defs[use]
        fields: dict[str, list[float] | str] = {
            str(key): str(value)
            for key, value in element.attrib.items()
            if key not in ("DEF", "containerField")
        }
        node = _Node(etree.QName(element).localname, fields)
        name = element.get("DEF")
        if name:
            defs[name] = node
        node.kids = [convert(child) for child in element if isinstance(child.tag, str)]
        return node

    for child in root:
        if not isinstance(child.tag, str):
            continue
        name = etree.QName(child).localname
        if name == "head":
            for unit in child:
                is_length = isinstance(unit.tag, str) and unit.get("category") == "length"
                if is_length and etree.QName(unit).localname == "unit":
                    metres_per_unit = float(unit.get("conversionFactor", "1"))
        elif name == "Scene":
            scene = convert(child)
    if scene is None:
        raise ValueError("the X3D document has no Scene")
    if metres_per_unit is not None and not metres_per_unit > 0:
        raise ValueError("the X3D length unit's conversionFactor must be positive")
    return scene, metres_per_unit


# --- VRML97 ---------------------------------------------------------------------------------

# X3D ClassicVRML header statements and how many tokens each takes (keyword included).
_X3D_STATEMENTS = {"PROFILE": 2, "COMPONENT": 2, "META": 3, "UNIT": 4, "IMPORT": 2, "EXPORT": 2}
_TOKEN = re.compile(r'[\s,]+|#[^\n\r]*|("(?:[^"\\]|\\.)*")|([{}\[\]])|([^\s,{}\[\]"#]+)')


def _tokens(text: str) -> Iterator[str]:
    for match in _TOKEN.finditer(text):
        token = match.group(1) or match.group(2) or match.group(3)
        if token:
            yield token


class _Vrml:
    """A recursive-descent reader for the VRML97 node syntax (no PROTO).

    With `x3d` it also reads X3D ClassicVRML's own statements: PROFILE, COMPONENT, META,
    IMPORT/EXPORT (all skipped) and UNIT, whose length factor it keeps.
    """

    def __init__(self, text: str, *, x3d: bool = False) -> None:
        self._tokens = _tokens(text)
        self._next: str | None = next(self._tokens, None)
        self.defs: dict[str, _Node] = {}
        self.depth = 0
        self.x3d = x3d
        self.metres_per_unit: float | None = None

    def peek(self) -> str | None:
        return self._next

    def take(self) -> str:
        token = self._next
        if token is None:
            raise ValueError("the VRML file ends in the middle of a node")
        self._next = next(self._tokens, None)
        return token

    def expect(self, wanted: str) -> None:
        got = self.take()
        if got != wanted:
            raise ValueError(f"expected {wanted!r}, found {got!r}")

    def statement(self) -> _Node | None:
        token = self.peek()
        if token in ("PROTO", "EXTERNPROTO"):
            raise ValueError("VRML PROTO/EXTERNPROTO is not supported; export without prototypes")
        if token == "ROUTE":  # ROUTE a.b TO c.d: event wiring, nothing to mesh
            for _ in range(4):
                self.take()
            return None
        if self.x3d and token in _X3D_STATEMENTS:
            words = [self.take() for _ in range(_X3D_STATEMENTS[token])]
            if token in ("IMPORT", "EXPORT") and self.peek() == "AS":
                self.take(), self.take()
            if token == "UNIT" and words[1] == "length":
                if not _NUMBER.fullmatch(words[3]) or not float(words[3]) > 0:
                    raise ValueError("the X3D length UNIT's conversion factor must be positive")
                self.metres_per_unit = float(words[3])
            return None
        return self.node()

    def node(self) -> _Node | None:
        token = self.take()
        if token == "NULL":
            return None
        if token == "USE":
            used = self.take()
            if used not in self.defs:
                raise ValueError(f"USE {used!r} comes before its DEF")
            return self.defs[used]
        name: str | None = None
        if token == "DEF":
            name, token = self.take(), self.take()
        if not _IDENT.match(token):
            raise ValueError(f"expected a node type, found {token!r}")
        node = _Node(token)
        if name:
            self.defs[name] = node
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ValueError(f"VRML nodes nest deeper than {MAX_DEPTH} levels")
        self.expect("{")
        while self.peek() != "}":
            if self.peek() is None:
                raise ValueError(f"the {node.type} node is never closed")
            if self.peek() in ("PROTO", "EXTERNPROTO", "ROUTE"):
                self.statement()
                continue
            self.field(node, self.take())
        self.take()
        self.depth -= 1
        return node

    def field(self, node: _Node, name: str) -> None:
        token = self.peek()
        if token == "[":
            self.take()
            numbers: list[float] = []
            words: list[str] = []
            while self.peek() != "]":
                item = self.peek()
                if item is None:
                    raise ValueError(f"the {node.type}.{name} list is never closed")
                if _NUMBER.fullmatch(item):
                    numbers.append(float(self.take()))
                elif item.startswith('"') or item in ("TRUE", "FALSE"):
                    words.append(self.take())
                else:
                    kid = self.node()
                    if kid is not None:
                        node.kids.append(kid)
            self.take()
            if numbers:
                node.fields[name] = numbers
            elif words:
                node.fields[name] = " ".join(words)
        elif token is not None and _NUMBER.fullmatch(token):
            numbers = []
            while (item := self.peek()) is not None and _NUMBER.fullmatch(item):
                numbers.append(float(self.take()))
            node.fields[name] = numbers
        elif token is not None and (token.startswith('"') or token in ("TRUE", "FALSE")):
            node.fields[name] = self.take()
        else:
            kid = self.node()
            if kid is not None:
                node.kids.append(kid)


def _statements(reader: _Vrml) -> _Node:
    root = _Node("Group")
    while reader.peek() is not None:
        node = reader.statement()
        if node is not None:
            root.kids.append(node)
    return root


def _read_wrl(data: bytes) -> _Node:
    text = data.decode("utf-8", errors="replace")
    header = text.lstrip("﻿")[:32]
    if header.startswith("#VRML V1.0"):
        raise ValueError("VRML 1.0 is not supported; export as VRML97 (V2.0)")
    if not header.startswith("#VRML V2.0"):
        raise ValueError("not a VRML97 file (no '#VRML V2.0' header)")
    return _statements(_Vrml(text))


def _read_x3dv(data: bytes) -> tuple[_Node, float | None]:
    """X3D in the ClassicVRML encoding: the scene and its UNIT length factor, if any."""
    text = data.decode("utf-8", errors="replace")
    if not re.match(r"#X3D V[34]\.\d", text.lstrip("﻿")):
        raise ValueError("not an X3D ClassicVRML file (no '#X3D V3.x' or 'V4.x' header)")
    reader = _Vrml(text, x3d=True)
    root = _statements(reader)
    return root, reader.metres_per_unit


def _read(data: bytes, format_id: str) -> tuple[_Node, float | None]:
    if format_id == "x3d":
        return _read_x3d(data)
    if format_id == "x3dv":
        return _read_x3dv(data)
    if format_id == "wrl":
        return _read_wrl(data), None
    raise ValueError(f"not a Web3D format: {format_id!r}")


# --- entry points ---------------------------------------------------------------------------


def load_mesh(path: Path, format_id: str) -> tuple[trimesh.Trimesh, float, dict[str, int]]:
    """The whole scene as one Z-up mesh in the file's own units, metres-per-unit, skips."""
    scene, declared = _read(path.read_bytes(), format_id)
    mesh, skipped = _collect(scene)
    return mesh, declared if declared is not None else 1.0, skipped


def parse_web3d_file(path: Path, format_id: str) -> ImportMetadata:
    scene, declared = _read(path.read_bytes(), format_id)
    mesh, skipped = _collect(scene)
    metres = declared if declared is not None else 1.0
    scale = metres * 1000.0
    spec = "VRML97" if format_id == "wrl" else "X3D"
    source_units = f"{metres:g} * meter" if declared is not None else f"meter ({spec} default)"

    warnings: list[Warning] = [
        warn(
            "unsupported_geometry",
            Severity.warning,
            f"{count} {kind} node(s) were left out"
            + (" (external files are never fetched)" if kind == "Inline" else ""),
            node=kind,
            count=count,
        )
        for kind, count in sorted(skipped.items())
    ]
    if mesh.is_empty:
        return ImportMetadata(
            format=format_id,
            representation="scene",
            unit_source="file",
            source_units=source_units,
            scale_to_mm=scale,
            bbox=None,
            mesh=None,
            warnings=[*warnings, warn("empty_geometry", Severity.error, "no mesh geometry found")],
            parser=PARSER,
        )
    stats, mesh_warnings = mesh_stats(mesh, scale=scale)
    bbox = bbox_of(mesh, scale=scale)
    warnings.extend(mesh_warnings)
    warnings.extend(extent_warnings(bbox))
    if declared is None and float(np.max(mesh.extents)) > SUSPICIOUS_METRES:
        warnings.append(
            warn(
                "units_suspicious",
                Severity.info,
                f"{spec} is metres by definition, and this model is over "
                f"{SUSPICIOUS_METRES:g} m across — the exporter may have written millimetres",
            )
        )
    return ImportMetadata(
        format=format_id,
        representation="scene",
        unit_source="file",
        source_units=source_units,
        scale_to_mm=scale,
        bbox=bbox,
        mesh=stats,
        warnings=warnings,
        parser=PARSER,
    )


def _y_up_metres(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Platform mm, Z-up -> Web3D metres, Y-up (both formats' defaults)."""
    vertices = np.asarray(mesh.vertices, dtype=float) @ Z_UP_TO_Y_UP[:3, :3].T * 0.001
    return vertices, np.asarray(mesh.faces, dtype=np.int64)


def _joined(vertices: np.ndarray, faces: np.ndarray) -> tuple[str, str]:
    rows = np.char.mod("%.9g", vertices)
    points = ", ".join(" ".join(row) for row in rows)
    index = " ".join(f"{a} {b} {c} -1" for a, b, c in faces.tolist())
    return points, index


def write_x3d(mesh: trimesh.Trimesh, output_path: Path) -> None:
    """No UNIT statement: plain metres read correctly everywhere, a UNIT only in X3D 3.3+."""
    points, index = _joined(*_y_up_metres(mesh))
    output_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<X3D profile="Interchange" version="3.3">\n'
        "  <head>\n"
        '    <meta name="generator" content="Physical AI 3D"/>\n'
        '    <meta name="description" content="Y-up, metres (the X3D defaults)"/>\n'
        "  </head>\n"
        "  <Scene>\n"
        "    <Shape>\n"
        f'      <IndexedFaceSet solid="true" ccw="true" coordIndex="{index}">\n'
        f'        <Coordinate point="{points}"/>\n'
        "      </IndexedFaceSet>\n"
        "    </Shape>\n"
        "  </Scene>\n"
        "</X3D>\n",
        encoding="utf-8",
        newline="\n",
    )


def write_wrl(mesh: trimesh.Trimesh, output_path: Path) -> None:
    _write_classic(mesh, output_path, "#VRML V2.0 utf8\n", "VRML97")


def write_x3dv(mesh: trimesh.Trimesh, output_path: Path) -> None:
    _write_classic(mesh, output_path, "#X3D V3.3 utf8\nPROFILE Interchange\n", "X3D")


def _write_classic(mesh: trimesh.Trimesh, output_path: Path, header: str, spec: str) -> None:
    """VRML97 and X3D ClassicVRML share the node syntax; only the header differs."""
    points, index = _joined(*_y_up_metres(mesh))
    output_path.write_text(
        header + f"# Physical AI 3D export: metres and Y-up, as {spec} defines them.\n"
        "Shape {\n"
        "  geometry IndexedFaceSet {\n"
        "    solid TRUE\n"
        "    ccw TRUE\n"
        f"    coord Coordinate {{ point [ {points} ] }}\n"
        f"    coordIndex [ {index} ]\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
        newline="\n",
    )
