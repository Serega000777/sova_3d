"""Direct mesh editing and surface details (T-235 / T-236, F-086).

A selection names the geometry a person picked by *position*, not by index: the client's
vertex/edge/face ids belong to a welded copy of the mesh it drew, so the request carries the
millimetre coordinates of the picked vertices (one point per vertex, two per edge, three per
face) and this module finds them again in its own mesh. A selection that no longer lines up
with the mesh is refused as stale instead of guessed at.

Operations run in order on one mesh and every result is validated: if the source was
watertight the result must be, and the report lists any repair that was needed to get there.
Nothing is written when validation fails. Booleans are manifold's, so surface details on a
watertight mesh stay watertight by construction.
"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import manifold3d as m3d
import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.spatial import cKDTree
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from worker import repair as mesh_repair
from worker.importers.common import as_single_mesh, to_platform_axes

Vec3 = tuple[float, float, float]

POSITION_TOL_MM = 5e-3
MAX_SELECTION_POINTS = 30_000
MAX_OPERATIONS = 32
MAX_FACES_AFTER = 2_000_000
MAX_CUTTERS = 4_000
MAX_DELETE_FACES = 20_000
FOOTPRINT_SAMPLES = 9  # samples per axis when checking that a footprint lies on a flat surface
FLAT_TOL_MM = 0.02
FLAT_ANGLE_DEG = 3.0
KNURL_OPENING = 0.85  # groove width at the surface, as a share of the pitch
KNURL_FLOOR = 0.1  # flat floor width at the groove bottom, as a share of the pitch


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditError(Exception):
    """A request the mesh cannot honour; carries a stable machine code."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# --- request ---------------------------------------------------------------------------------


class Selection(Strict):
    """Picked components as millimetre coordinates: 1 point per vertex, 2 per edge, 3 per face."""

    kind: Literal["vertex", "edge", "face"]
    points_mm: list[Vec3] = Field(min_length=1, max_length=MAX_SELECTION_POINTS)

    @model_validator(mode="after")
    def _arity(self) -> Selection:
        per = {"vertex": 1, "edge": 2, "face": 3}[self.kind]
        if len(self.points_mm) % per:
            raise ValueError(f"a {self.kind} selection needs {per} points per component")
        return self


class FaceSelection(Selection):
    kind: Literal["face"] = "face"


class EdgeSelection(Selection):
    kind: Literal["edge"] = "edge"


class MoveOp(Strict):
    op: Literal["move"] = "move"
    selection: Selection
    delta_mm: Vec3 | None = None
    along_normal_mm: float | None = None

    @model_validator(mode="after")
    def _one_way(self) -> MoveOp:
        if (self.delta_mm is None) == (self.along_normal_mm is None):
            raise ValueError("give exactly one of delta_mm and along_normal_mm")
        return self


ScaleFactor = Annotated[float, Field(ge=0.1, le=10.0)]


class ScaleOp(Strict):
    """Scale selected components around the centre of their selected bounding box."""

    op: Literal["scale"] = "scale"
    selection: Selection
    factors: tuple[ScaleFactor, ScaleFactor, ScaleFactor]

    @model_validator(mode="after")
    def _changes_size(self) -> ScaleOp:
        if all(abs(factor - 1.0) <= 1e-9 for factor in self.factors):
            raise ValueError("at least one scale factor must differ from 1")
        return self


class RotateOp(Strict):
    """Rotate selected components around a world axis through their selected bounds centre."""

    op: Literal["rotate"] = "rotate"
    selection: Selection
    axis: Literal["x", "y", "z"]
    angle_deg: Annotated[float, Field(gt=-360.0, lt=360.0)]

    @model_validator(mode="after")
    def _changes_angle(self) -> RotateOp:
        if abs(self.angle_deg) <= 1e-9:
            raise ValueError("rotation angle must not be zero")
        return self


class ExtrudeOp(Strict):
    op: Literal["extrude"] = "extrude"
    selection: FaceSelection
    distance_mm: float


class InsetOp(Strict):
    op: Literal["inset"] = "inset"
    selection: FaceSelection
    amount_mm: Annotated[float, Field(gt=0)]


class DeleteFacesOp(Strict):
    op: Literal["delete_faces"] = "delete_faces"
    selection: FaceSelection
    fill: bool = True


class BevelEdgesOp(Strict):
    """`width_mm` is how far the bevel reaches along each adjoining face. One segment is a
    straight chamfer; more segments round it into a fillet of that reach."""

    op: Literal["bevel_edges"] = "bevel_edges"
    selection: EdgeSelection
    width_mm: Annotated[float, Field(gt=0)]
    segments: Annotated[int, Field(ge=1, le=16)] = 1


class Circle(Strict):
    shape: Literal["circle"] = "circle"
    diameter_mm: Annotated[float, Field(gt=0)]


class Square(Strict):
    shape: Literal["square"] = "square"
    width_mm: Annotated[float, Field(gt=0)]
    height_mm: Annotated[float, Field(gt=0)] | None = None  # None = a true square
    rotation_deg: float = 0.0


class Area(Strict):
    width_mm: Annotated[float, Field(gt=0)]
    length_mm: Annotated[float, Field(gt=0)]
    rotation_deg: float = 0.0


class Ribs(Strict):
    """Parallel bars (raised) or grooves (recessed) running along the area's length."""

    shape: Literal["ribs"] = "ribs"
    area: Area
    pitch_mm: Annotated[float, Field(gt=0)]
    rib_width_mm: Annotated[float, Field(gt=0)]
    angle_deg: float = 0.0  # from the area's length axis; the area clips the ribs


class Knurl(Strict):
    """V-grooves cut into the surface: one set (straight) or two crossing sets (diamond)."""

    shape: Literal["knurl"] = "knurl"
    area: Area
    pattern: Literal["straight", "diamond"] = "diamond"
    pitch_mm: Annotated[float, Field(gt=0)]
    angle_deg: float = 45.0  # straight: groove angle; diamond: each set is at +/- this angle


Profile = Annotated[Circle | Square | Ribs | Knurl, Field(discriminator="shape")]


class DetailOp(Strict):
    """A dimensioned feature on a flat patch of the surface, raised from it or cut into it."""

    op: Literal["detail"] = "detail"
    at_mm: Vec3
    normal_hint: Vec3 | None = None
    profile: Profile
    mode: Literal["raised", "recessed"] = "raised"
    depth_mm: Annotated[float, Field(gt=0)]


Operation = Annotated[
    MoveOp | ScaleOp | RotateOp | ExtrudeOp | InsetOp | DeleteFacesOp | BevelEdgesOp | DetailOp,
    Field(discriminator="op"),
]


class EditRequest(Strict):
    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)
    preview: bool = False
    # How many source triangles the selection was made on, so a changed mesh is caught.
    expected_faces: int | None = None
    # Features below this are refused instead of producing slivers (print/export tolerance).
    tolerance_mm: Annotated[float, Field(gt=0)] = 0.2


# --- report ----------------------------------------------------------------------------------


class Stats(BaseModel):
    faces: int
    vertices: int
    volume_mm3: float | None
    watertight: bool
    bbox_mm: tuple[Vec3, Vec3]


class Applied(BaseModel):
    op: str
    detail: dict[str, Any] = Field(default_factory=dict)


class Preview(BaseModel):
    footprints_mm: list[list[Vec3]] = Field(default_factory=list)
    estimated_added_triangles: int = 0


class EditReport(BaseModel):
    ok: bool
    code: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    failed_operation: int | None = None
    applied: list[Applied] = Field(default_factory=list)
    before: Stats | None = None
    after: Stats | None = None
    warnings: list[str] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
    preview: Preview | None = None
    output_path: str | None = None


def _stats(mesh: trimesh.Trimesh) -> Stats:
    bounds = mesh.bounds if len(mesh.vertices) else np.zeros((2, 3))
    watertight = bool(mesh.is_watertight)
    return Stats(
        faces=len(mesh.faces),
        vertices=len(mesh.vertices),
        volume_mm3=float(mesh.volume) if watertight else None,
        watertight=watertight,
        bbox_mm=(
            (float(bounds[0][0]), float(bounds[0][1]), float(bounds[0][2])),
            (float(bounds[1][0]), float(bounds[1][1]), float(bounds[1][2])),
        ),
    )


# --- selections ------------------------------------------------------------------------------


class _Locator:
    """Finds a picked point, edge or triangle again in the current mesh."""

    def __init__(self, mesh: trimesh.Trimesh) -> None:
        self.mesh = mesh
        self.tree = cKDTree(mesh.vertices)
        self.faces = {tuple(sorted(int(v) for v in f)): i for i, f in enumerate(mesh.faces)}

    def vertex(self, point: Vec3) -> int:
        distance, index = self.tree.query(point)
        if distance > POSITION_TOL_MM:
            raise EditError(
                "stale_selection",
                "a selected vertex is no longer on the mesh; select again",
                point_mm=list(point),
            )
        return int(index)

    def vertices(self, selection: Selection) -> np.ndarray:
        """Vertex ids a selection touches, ascending and unique."""
        ids = [self.vertex(p) for p in selection.points_mm]
        return np.unique(np.array(ids, dtype=np.int64))

    def face_ids(self, selection: Selection) -> np.ndarray:
        ids = [self.vertex(p) for p in selection.points_mm]
        found: list[int] = []
        for i in range(0, len(ids), 3):
            key = tuple(sorted(ids[i : i + 3]))
            face = self.faces.get(key)
            if face is None:
                raise EditError("stale_selection", "a selected face is no longer on the mesh")
            found.append(face)
        return np.unique(np.array(found, dtype=np.int64))

    def edge_pairs(self, selection: Selection) -> list[tuple[int, int]]:
        ids = [self.vertex(p) for p in selection.points_mm]
        pairs: list[tuple[int, int]] = []
        for i in range(0, len(ids), 2):
            a, b = ids[i], ids[i + 1]
            if a == b:
                raise EditError("stale_selection", "a selected edge collapsed to a point")
            pairs.append((min(a, b), max(a, b)))
        return sorted(set(pairs))


# --- move ------------------------------------------------------------------------------------


def _move(mesh: trimesh.Trimesh, loc: _Locator, op: MoveOp) -> dict[str, Any]:
    ids = loc.vertices(op.selection)
    vertices = np.array(mesh.vertices, dtype=np.float64)
    if op.delta_mm is not None:
        offset = np.array(op.delta_mm, dtype=np.float64)
        vertices[ids] += offset
        moved = float(np.linalg.norm(offset))
    else:
        normals = np.array(mesh.vertex_normals, dtype=np.float64)[ids]
        vertices[ids] += normals * float(op.along_normal_mm or 0.0)
        moved = abs(float(op.along_normal_mm or 0.0))
    mesh.vertices = vertices
    return {"vertices": int(len(ids)), "distance_mm": round(moved, 6)}


def _selection_pivot(vertices: np.ndarray) -> np.ndarray:
    """Stable gizmo pivot: the centre of the selected vertices' axis-aligned bounds."""
    return np.asarray((vertices.min(axis=0) + vertices.max(axis=0)) / 2.0, dtype=np.float64)


def _scale(mesh: trimesh.Trimesh, loc: _Locator, op: ScaleOp) -> dict[str, Any]:
    ids = loc.vertices(op.selection)
    vertices = np.array(mesh.vertices, dtype=np.float64)
    pivot = _selection_pivot(vertices[ids])
    factors = np.array(op.factors, dtype=np.float64)
    transformed = pivot + (vertices[ids] - pivot) * factors
    if float(np.max(np.linalg.norm(transformed - vertices[ids], axis=1))) <= 1e-9:
        raise EditError("no_effect", "the selected components do not move under that scale")
    vertices[ids] = transformed
    mesh.vertices = vertices
    return {
        "vertices": int(len(ids)),
        "pivot_mm": [round(float(value), 6) for value in pivot],
        "factors": [float(value) for value in factors],
    }


def _rotate_selection(mesh: trimesh.Trimesh, loc: _Locator, op: RotateOp) -> dict[str, Any]:
    ids = loc.vertices(op.selection)
    vertices = np.array(mesh.vertices, dtype=np.float64)
    pivot = _selection_pivot(vertices[ids])
    angle = math.radians(op.angle_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    matrices = {
        "x": np.array([[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]]),
        "y": np.array([[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]]),
        "z": np.array([[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]]),
    }
    # Vertices are row vectors here, hence the transpose of the conventional column matrix.
    transformed = pivot + (vertices[ids] - pivot) @ matrices[op.axis].T
    if float(np.max(np.linalg.norm(transformed - vertices[ids], axis=1))) <= 1e-9:
        raise EditError("no_effect", "the selected components do not move around that axis")
    vertices[ids] = transformed
    mesh.vertices = vertices
    return {
        "vertices": int(len(ids)),
        "pivot_mm": [round(float(value), 6) for value in pivot],
        "axis": op.axis,
        "angle_deg": op.angle_deg,
    }


# --- extrude / inset -------------------------------------------------------------------------


def _regions(mesh: trimesh.Trimesh, face_ids: np.ndarray) -> list[np.ndarray]:
    """Connected groups of the selected faces (joined across shared edges)."""
    chosen = set(int(f) for f in face_ids)
    adjacency = mesh.face_adjacency
    parent = {f: f for f in chosen}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in adjacency:
        if int(a) in chosen and int(b) in chosen:
            parent[find(int(a))] = find(int(b))
    groups: dict[int, list[int]] = {}
    for f in chosen:
        groups.setdefault(find(f), []).append(f)
    return [np.array(sorted(g), dtype=np.int64) for g in groups.values()]


def _boundary_edges(faces: np.ndarray) -> list[tuple[int, int]]:
    """Directed edges used by exactly one of `faces`, as they run inside that face."""
    directed = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    keys = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    once = counts[inverse.reshape(-1)] == 1
    return [(int(a), int(b)) for a, b in directed[once]]


def _extrude_region(
    mesh: trimesh.Trimesh,
    region: np.ndarray,
    *,
    boundary_only: bool,
    offsets: Callable[[np.ndarray, list[tuple[int, int]]], dict[int, np.ndarray]],
) -> None:
    """Lift `region` off the mesh and join it back with a wall of triangles.

    Selected faces are re-pointed at duplicated vertices (all of the region's vertices for an
    extrusion, only its boundary for an inset); each boundary edge a->b gets the wall
    (a, b, b') and (a, b', a'), which keeps every edge shared by exactly two faces.
    """
    faces = np.array(mesh.faces, dtype=np.int64)
    region_faces = faces[region]
    boundary = _boundary_edges(region_faces)
    if not boundary:
        raise EditError("closed_selection", "the selection has no edge to extrude from")
    moved = offsets(region_faces, boundary)
    if boundary_only:
        dup = sorted({v for e in boundary for v in e})
    else:
        dup = sorted({int(v) for v in region_faces.reshape(-1)})
    vertices = np.array(mesh.vertices, dtype=np.float64)
    new_index = {v: len(vertices) + i for i, v in enumerate(dup)}
    extra = np.array([vertices[v] + moved.get(v, np.zeros(3)) for v in dup], dtype=np.float64)
    remapped = np.vectorize(lambda v: new_index.get(int(v), int(v)))(region_faces)
    faces[region] = remapped
    wall: list[list[int]] = []
    for a, b in boundary:
        ap, bp = new_index[a], new_index[b]
        wall.append([a, b, bp])
        wall.append([a, bp, ap])
    mesh.vertices = np.vstack([vertices, extra])
    mesh.faces = np.vstack([faces, np.array(wall, dtype=np.int64)])


def _region_normal(mesh: trimesh.Trimesh, region: np.ndarray) -> np.ndarray:
    areas = mesh.area_faces[region][:, None]
    total = (np.array(mesh.face_normals)[region] * areas).sum(axis=0)
    length = float(np.linalg.norm(total))
    if length < 1e-12:
        raise EditError(
            "degenerate_selection", "the selected faces cancel out; pick a flatter patch"
        )
    return np.asarray(total / length, dtype=np.float64)


def _extrude(mesh: trimesh.Trimesh, loc: _Locator, op: ExtrudeOp) -> dict[str, Any]:
    if abs(op.distance_mm) < 1e-6:
        raise EditError("zero_distance", "extrusion distance must not be zero")
    regions = _regions(mesh, loc.face_ids(op.selection))
    # Faces and normals are read once, before any region changes the mesh underneath them.
    normals = [_region_normal(mesh, r) for r in regions]
    for region, normal in zip(regions, normals, strict=True):
        shift = normal * op.distance_mm

        def offsets(
            rf: np.ndarray, _b: list[tuple[int, int]], shift: np.ndarray = shift
        ) -> dict[int, np.ndarray]:
            return {int(v): shift for v in np.unique(rf)}

        _extrude_region(mesh, region, boundary_only=False, offsets=offsets)
    return {"regions": len(regions), "faces": int(sum(len(r) for r in regions))}


def _inset(mesh: trimesh.Trimesh, loc: _Locator, op: InsetOp) -> dict[str, Any]:
    regions = _regions(mesh, loc.face_ids(op.selection))
    before_normals = np.array(mesh.face_normals, dtype=np.float64)
    for region in regions:
        face_normals = before_normals[region]

        def offsets(
            rf: np.ndarray,
            boundary: list[tuple[int, int]],
            region: np.ndarray = region,
            face_normals: np.ndarray = face_normals,
        ) -> dict[int, np.ndarray]:
            vertices = np.array(mesh.vertices, dtype=np.float64)
            inward: dict[int, list[np.ndarray]] = {}
            face_of = {
                tuple(int(v) for v in np.roll(rf[i], -k)[:2]): i
                for i in range(len(rf))
                for k in range(3)
            }
            for a, b in boundary:
                i = face_of[(a, b)]
                normal = face_normals[i]
                direction = np.cross(normal, vertices[b] - vertices[a])
                length = float(np.linalg.norm(direction))
                if length < 1e-12:
                    continue
                unit = direction / length
                inward.setdefault(a, []).append(unit)
                inward.setdefault(b, []).append(unit)
            result: dict[int, np.ndarray] = {}
            for v, units in inward.items():
                total = np.sum(units, axis=0)
                if len(units) == 2:
                    scale = 1.0 + float(np.dot(units[0], units[1]))
                    step = total / max(scale, 0.3)  # miter, capped so sharp corners stay sane
                else:
                    length = float(np.linalg.norm(total))
                    step = total / length if length > 1e-12 else np.zeros(3)
                result[v] = step * op.amount_mm
            return result

        _extrude_region(mesh, region, boundary_only=True, offsets=offsets)
        # An inset that overshoots turns faces inside out; refuse it instead of keeping them.
        new_normals = np.array(mesh.face_normals, dtype=np.float64)[region]
        flipped = int(np.count_nonzero(np.einsum("ij,ij->i", new_normals, face_normals) < 0.0))
        if flipped:
            raise EditError(
                "inset_too_large",
                f"an inset of {op.amount_mm:g} mm folds {flipped} faces over; use a smaller amount",
                flipped_faces=flipped,
            )
    return {"regions": len(regions), "amount_mm": op.amount_mm}


# --- delete + fill ---------------------------------------------------------------------------


def _delete_faces(
    mesh: trimesh.Trimesh, loc: _Locator, op: DeleteFacesOp, warnings: list[str]
) -> dict[str, Any]:
    ids = loc.face_ids(op.selection)
    if len(ids) > MAX_DELETE_FACES:
        raise EditError(
            "region_too_large",
            f"deleting {len(ids)} faces exceeds the bounded region of {MAX_DELETE_FACES}",
        )
    if len(ids) >= len(mesh.faces):
        raise EditError("everything_selected", "that would delete the whole mesh")
    was_watertight = bool(mesh.is_watertight)
    keep = np.ones(len(mesh.faces), dtype=bool)
    keep[ids] = False
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    filled = 0
    remaining = 0
    if op.fill and was_watertight:
        filled, remaining = mesh_repair.close_holes(mesh)
        if remaining:
            raise EditError(
                "hole_not_filled",
                f"{remaining} boundary loop(s) could not be filled; the region is too irregular",
                remaining_loops=remaining,
            )
    elif not op.fill:
        warnings.append("faces were deleted without filling: the mesh now has an open boundary")
    return {"faces": int(len(ids)), "holes_filled": int(filled)}


# --- bevel -----------------------------------------------------------------------------------


def _manifold(mesh: trimesh.Trimesh) -> m3d.Manifold:
    solid = m3d.Manifold(
        m3d.Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )
    if solid.status() != m3d.Error.NoError:
        raise EditError("not_manifold", f"the mesh is not a valid solid ({solid.status().name})")
    return solid


def _from_manifold(solid: m3d.Manifold) -> trimesh.Trimesh:
    out = solid.to_mesh()
    mesh = trimesh.Trimesh(
        vertices=np.asarray(out.vert_properties)[:, :3].astype(np.float64),
        faces=np.asarray(out.tri_verts).astype(np.int64),
        process=False,
    )
    mesh.merge_vertices()
    return mesh


def _extruded(polygon: Polygon, height: float, frame: np.ndarray) -> trimesh.Trimesh:
    """A prism of `polygon` (z from 0 to `height`) placed by the 4x4 `frame`."""
    prism: trimesh.Trimesh = trimesh.creation.extrude_polygon(polygon, height)
    if prism.volume < 0:
        prism.invert()
    prism.apply_transform(frame)
    return prism


def _frame(origin: np.ndarray, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 0] = x
    matrix[:3, 1] = y
    matrix[:3, 2] = z
    matrix[:3, 3] = origin
    return matrix


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        raise EditError("degenerate_geometry", "zero-length direction")
    return vector / length


def _bevel(
    mesh: trimesh.Trimesh, loc: _Locator, op: BevelEdgesOp, warnings: list[str]
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    if not mesh.is_watertight:
        raise EditError("needs_watertight", "bevelling needs a watertight mesh; repair it first")
    pairs = loc.edge_pairs(op.selection)
    if len(pairs) > MAX_CUTTERS:
        raise EditError(
            "too_many_features",
            f"{len(pairs)} edges exceed the limit of {MAX_CUTTERS}; select fewer edges",
        )
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, face in enumerate(mesh.faces):
        for i in range(3):
            a, b = int(face[i]), int(face[(i + 1) % 3])
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(face_index)
    normals = np.array(mesh.face_normals, dtype=np.float64)
    vertices = np.array(mesh.vertices, dtype=np.float64)
    cutters: list[trimesh.Trimesh] = []
    skipped = 0
    for a, b in pairs:
        faces = edge_faces.get((a, b), [])
        if len(faces) != 2:
            skipped += 1
            continue
        f1, f2 = faces
        n1, n2 = normals[f1], normals[f2]
        # The corner angle the solid makes at this edge: 180 degrees minus the angle between the
        # outward normals. A coplanar pair has nothing to bevel.
        cos_between = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
        between = math.acos(cos_between)
        if between < math.radians(5.0):
            skipped += 1
            continue
        edge = vertices[b] - vertices[a]
        length = float(np.linalg.norm(edge))
        u = edge / length
        opposite = []
        for f in (f1, f2):
            third = next(int(v) for v in mesh.faces[f] if int(v) not in (a, b))
            across = vertices[third] - vertices[a]
            tangent = across - np.dot(across, u) * u
            opposite.append(_unit(tangent))
        t1, t2 = opposite
        # Convex means the far vertex of each face lies behind the other face's plane.
        far2 = vertices[next(int(v) for v in mesh.faces[f2] if int(v) not in (a, b))] - vertices[a]
        if float(np.dot(n1, far2)) > 1e-9:
            skipped += 1  # a concave edge: a cutter would add material, not remove it
            continue
        alpha = math.acos(float(np.clip(np.dot(t1, t2), -1.0, 1.0)))  # interior angle
        reach = op.width_mm
        x_axis = t1
        y_axis = _unit(np.cross(u, t1))  # (t1, y, u) is right-handed, so the prism is not mirrored

        def local(
            point: np.ndarray,
            origin: np.ndarray = vertices[a],
            xa: np.ndarray = x_axis,
            ya: np.ndarray = y_axis,
        ) -> tuple[float, float]:
            d = point - origin
            return float(np.dot(d, xa)), float(np.dot(d, ya))

        e0 = np.zeros(2)
        p1 = np.array(local(vertices[a] + t1 * reach))
        p2 = np.array(local(vertices[a] + t2 * reach))
        out_dir = -(np.array(local(vertices[a] + t1)) + np.array(local(vertices[a] + t2)))
        out_dir = out_dir / max(float(np.linalg.norm(out_dir)), 1e-12)
        apex = e0 + out_dir * (2.0 * reach)
        nudge = 1e-3 * reach
        # lift the endpoints a hair outside their faces so the cutter never grazes them
        o1 = np.array(local(vertices[a] + n1 * nudge + t1 * reach))
        o2 = np.array(local(vertices[a] + n2 * nudge + t2 * reach))
        ring: list[np.ndarray] = [apex, o1]
        if op.segments > 1:
            radius = reach * math.tan(alpha / 2.0)
            bisector = _unit(t1 + t2)
            centre = np.array(local(vertices[a] + bisector * (radius / math.sin(alpha / 2.0))))
            start = math.atan2(*(p1 - centre)[::-1])
            end = math.atan2(*(p2 - centre)[::-1])
            sweep = (end - start + math.pi) % (2.0 * math.pi) - math.pi
            for s in range(1, op.segments):
                angle = start + sweep * s / op.segments
                ring.append(centre + radius * np.array([math.cos(angle), math.sin(angle)]))
        ring.append(o2)
        polygon = Polygon([tuple(p) for p in ring])
        if not polygon.is_valid or polygon.area < 1e-9:
            skipped += 1
            continue
        margin = 1e-3 * max(length, 1.0)
        frame = _frame(vertices[a] - u * margin, x_axis, y_axis, u)
        cutters.append(_extruded(polygon, length + 2 * margin, frame))
    if not cutters:
        raise EditError(
            "nothing_to_bevel",
            "none of the selected edges can be bevelled (smooth, concave or open edges)",
            skipped=skipped,
        )
    if skipped:
        warnings.append(f"{skipped} selected edge(s) were skipped: smooth, concave or open")
    solid = _manifold(mesh)
    cut = m3d.Manifold.batch_boolean([_manifold(c) for c in cutters], m3d.OpType.Add)
    result = _from_manifold(solid - cut)
    return result, {
        "edges": len(cutters),
        "skipped": skipped,
        "style": "chamfer" if op.segments == 1 else "round",
    }


# --- surface details -------------------------------------------------------------------------


class _Surface:
    """A flat patch of the mesh: where it is, which way it faces, and a frame lying on it."""

    def __init__(self, origin: np.ndarray, normal: np.ndarray) -> None:
        self.origin = origin
        self.normal = normal
        helper = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        self.x = _unit(np.cross(helper, normal))
        self.y = np.cross(normal, self.x)

    def frame(self, z_offset: float = 0.0) -> np.ndarray:
        return _frame(self.origin + self.normal * z_offset, self.x, self.y, self.normal)

    def world(self, point2: tuple[float, float], z: float = 0.0) -> Vec3:
        p = self.origin + self.x * point2[0] + self.y * point2[1] + self.normal * z
        return (float(p[0]), float(p[1]), float(p[2]))


def _find_surface(mesh: trimesh.Trimesh, op: DetailOp) -> _Surface:
    point = np.array(op.at_mm, dtype=np.float64)
    closest, distance, triangle = trimesh.proximity.closest_point(  # type: ignore[no-untyped-call]
        mesh, [point]
    )
    if float(distance[0]) > 0.5:
        raise EditError(
            "off_surface",
            f"the chosen point is {float(distance[0]):.2f} mm from the surface; pick a point on it",
        )
    normal = np.array(mesh.face_normals[int(triangle[0])], dtype=np.float64)
    if op.normal_hint is not None:
        hint = _unit(np.array(op.normal_hint, dtype=np.float64))
        if float(np.dot(hint, normal)) < math.cos(math.radians(15.0)):
            raise EditError(
                "surface_ambiguous",
                "the point sits on an edge between differently facing surfaces; "
                "pick inside one face",
            )
    return _Surface(np.array(closest[0], dtype=np.float64), normal)


def _rotate(points: np.ndarray, degrees: float) -> np.ndarray:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.asarray(points @ np.array([[c, s], [-s, c]]), dtype=np.float64)


def _footprint(profile: Circle | Square | Ribs | Knurl) -> Polygon:
    if isinstance(profile, Circle):
        return ShapelyPoint(0, 0).buffer(profile.diameter_mm / 2.0, quad_segs=24)
    if isinstance(profile, Square):
        w = profile.width_mm / 2.0
        h = (profile.height_mm or profile.width_mm) / 2.0
        corners = np.array([[-w, -h], [w, -h], [w, h], [-w, h]])
        return Polygon(_rotate(corners, profile.rotation_deg))
    w, h = profile.area.width_mm / 2.0, profile.area.length_mm / 2.0
    corners = np.array([[-w, -h], [w, -h], [w, h], [-w, h]])
    return Polygon(_rotate(corners, profile.area.rotation_deg))


def _estimated_triangles(profile: Circle | Square | Ribs | Knurl) -> int:
    if isinstance(profile, Circle):
        return 24 * 4 * 2 + 48
    if isinstance(profile, Square):
        return 24
    diagonal = math.hypot(profile.area.width_mm, profile.area.length_mm)
    per_set = int(diagonal // profile.pitch_mm) + 1
    if isinstance(profile, Knurl) and profile.pattern == "diamond":
        cells = max(int(profile.area.width_mm // profile.pitch_mm), 1) * max(
            int(profile.area.length_mm // profile.pitch_mm), 1
        )
        return cells * 8 + 24
    return per_set * 12


def _check_tolerance(op: DetailOp, tolerance: float) -> None:
    profile = op.profile
    smallest: dict[str, float] = {"depth": op.depth_mm}
    if isinstance(profile, Circle):
        smallest["diameter"] = profile.diameter_mm
    elif isinstance(profile, Square):
        smallest["width"] = min(profile.width_mm, profile.height_mm or profile.width_mm)
    elif isinstance(profile, Ribs):
        smallest["rib width"] = profile.rib_width_mm
        smallest["gap between ribs"] = profile.pitch_mm - profile.rib_width_mm
        smallest["area"] = min(profile.area.width_mm, profile.area.length_mm)
    else:
        smallest["pitch"] = profile.pitch_mm / 2.0
        smallest["area"] = min(profile.area.width_mm, profile.area.length_mm)
    for name, value in smallest.items():
        if value < tolerance:
            raise EditError(
                "below_tolerance",
                f"the {name} ({value:g} mm) is below the {tolerance:g} mm tolerance; "
                "make the feature larger",
                feature=name,
                tolerance_mm=tolerance,
            )
    if isinstance(profile, Ribs) and profile.rib_width_mm >= profile.pitch_mm:
        raise EditError("ribs_overlap", "rib width must be smaller than the pitch")
    if isinstance(profile, Knurl) and not 5.0 <= abs(profile.angle_deg) <= 85.0:
        if profile.pattern == "diamond":
            raise EditError("bad_angle", "a diamond knurl needs an angle between 5 and 85 degrees")


def _footprint_samples(shape: Polygon) -> np.ndarray:
    minx, miny, maxx, maxy = shape.bounds
    xs = np.linspace(minx, maxx, FOOTPRINT_SAMPLES)
    ys = np.linspace(miny, maxy, FOOTPRINT_SAMPLES)
    grown = shape.buffer(1e-9)
    points = [(float(x), float(y)) for x in xs for y in ys if grown.contains(ShapelyPoint(x, y))]
    points.extend((float(x), float(y)) for x, y in shape.exterior.coords[:-1])
    return np.array(points, dtype=np.float64)


def _check_flat(mesh: trimesh.Trimesh, surface: _Surface, shape: Polygon) -> None:
    """The footprint must lie on one flat surface; probe it with rays instead of trusting it."""
    samples = _footprint_samples(shape)
    probe = 1.0
    origins = np.array(
        [
            surface.origin + surface.x * s[0] + surface.y * s[1] + surface.normal * probe
            for s in samples
        ]
    )
    directions = np.tile(-surface.normal, (len(samples), 1))
    locations, ray_index, triangle = mesh.ray.intersects_location(
        origins, directions, multiple_hits=False
    )
    hit = {int(r): (loc, int(t)) for r, loc, t in zip(ray_index, locations, triangle, strict=True)}
    off = 0
    for i in range(len(samples)):
        found = hit.get(i)
        if found is None:
            off += 1
            continue
        location, tri = found
        height = float(np.dot(location - surface.origin, surface.normal))
        tilt = float(np.dot(mesh.face_normals[tri], surface.normal))
        if abs(height) > FLAT_TOL_MM or tilt < math.cos(math.radians(FLAT_ANGLE_DEG)):
            off += 1
    if off:
        raise EditError(
            "footprint_leaves_surface",
            f"{off} of {len(samples)} sample points of the feature are off the flat surface; "
            "make it smaller or move it onto a flat area",
            off_surface=off,
            samples=len(samples),
        )


def _wall_behind(mesh: trimesh.Trimesh, surface: _Surface, shape: Polygon) -> float:
    """The thinnest material under the footprint, to keep a recess from cutting through."""
    samples = _footprint_samples(shape)
    origins = np.array(
        [
            surface.origin + surface.x * s[0] + surface.y * s[1] - surface.normal * 1e-3
            for s in samples
        ]
    )
    directions = np.tile(-surface.normal, (len(samples), 1))
    locations, ray_index, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=False)
    if len(ray_index) < len(samples):
        return math.inf  # no far wall found: open behind, treat as unconstrained
    return float(np.min(np.linalg.norm(locations - origins[ray_index], axis=1)))


def _bars(
    surface: _Surface,
    area: Area,
    pitch: float,
    angle_deg: float,
    section: Polygon,
) -> list[trimesh.Trimesh]:
    """Parallel prisms of `section` (x across, y up from the surface) that cover the area."""
    diagonal = math.hypot(area.width_mm, area.length_mm) + 2.0
    count = int(diagonal // pitch) + 1
    if count > MAX_CUTTERS:
        raise EditError(
            "too_many_features",
            f"{count} ribs or grooves exceed the limit of {MAX_CUTTERS}; "
            "use a larger pitch or area",
        )
    total = math.radians(area.rotation_deg + angle_deg)
    axis = surface.x * math.sin(total) + surface.y * math.cos(total)  # along the line
    across = surface.x * math.cos(total) - surface.y * math.sin(total)
    bars: list[trimesh.Trimesh] = []
    for k in range(-(count // 2), count // 2 + 1):
        # Section axes (across, normal) with the prism running along -axis keeps the basis
        # right-handed; the prism therefore starts at the far end of the line.
        origin = surface.origin + across * (k * pitch) + axis * (diagonal / 2.0)
        bars.append(_extruded(section, diagonal, _frame(origin, across, surface.normal, -axis)))
    return bars


def _area_prism(surface: _Surface, area: Area, below: float, above: float) -> trimesh.Trimesh:
    shape = _footprint(Ribs(area=area, pitch_mm=1.0, rib_width_mm=0.5))
    prism = _extruded(shape, below + above, surface.frame(-below))
    return prism


def _detail(
    mesh: trimesh.Trimesh,
    op: DetailOp,
    tolerance: float,
    preview: Preview | None,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    _check_tolerance(op, tolerance)
    if not mesh.is_watertight:
        raise EditError(
            "needs_watertight", "surface details need a watertight mesh; repair it first"
        )
    surface = _find_surface(mesh, op)
    profile = op.profile
    shape = _footprint(profile)
    _check_flat(mesh, surface, shape)
    if op.mode == "recessed":
        wall = _wall_behind(mesh, surface, shape)
        if wall < op.depth_mm + tolerance:
            raise EditError(
                "would_cut_through",
                f"the wall behind is {wall:.2f} mm; a {op.depth_mm:g} mm cut leaves less than "
                f"the {tolerance:g} mm tolerance",
                wall_mm=wall,
            )
    corners = [surface.world((c[0], c[1])) for c in list(shape.exterior.coords)[:-1]]
    estimate = _estimated_triangles(profile)
    if preview is not None:
        preview.footprints_mm.append(corners)
        preview.estimated_added_triangles += estimate
        return mesh, {"preview": True, "estimated_triangles": estimate}
    if len(mesh.faces) + estimate > MAX_FACES_AFTER:
        raise EditError("too_many_triangles", "the detail would make the mesh too large")

    embed = min(op.depth_mm * 0.5, 0.25)
    lip = max(0.05, op.depth_mm * 0.1)
    solid = _manifold(mesh)
    if isinstance(profile, Circle | Square):
        if op.mode == "raised":
            body = _extruded(shape, op.depth_mm + embed, surface.frame(-embed))
            result = solid + _manifold(body)
        else:
            body = _extruded(shape, op.depth_mm + lip, surface.frame(-op.depth_mm))
            result = solid - _manifold(body)
        count = 1
    elif isinstance(profile, Ribs):
        half = profile.rib_width_mm / 2.0
        if op.mode == "raised":
            section = Polygon(
                [(-half, -embed), (half, -embed), (half, op.depth_mm), (-half, op.depth_mm)]
            )
        else:
            section = Polygon(
                [(-half, -op.depth_mm), (half, -op.depth_mm), (half, lip), (-half, lip)]
            )
        bars = _bars(surface, profile.area, profile.pitch_mm, profile.angle_deg, section)
        clip = _manifold(
            _area_prism(surface, profile.area, below=op.depth_mm + 1.0, above=op.depth_mm + 1.0)
        )
        merged = m3d.Manifold.batch_boolean([_manifold(b) for b in bars], m3d.OpType.Add) ^ clip
        result = solid + merged if op.mode == "raised" else solid - merged
        count = len(bars)
    else:
        # Grooves (recessed) or ridges (raised) open to 85% of the pitch and keep a small flat
        # floor or tip. Features that meet at zero width, and V floors/tips that cross at a
        # single point, are valid for the boolean engine but pinch the mesh into non-manifold
        # vertices once triangles are merged on export.
        half = KNURL_OPENING * profile.pitch_mm / 2.0
        floor = KNURL_FLOOR * profile.pitch_mm / 2.0
        slope = (half - floor) / op.depth_mm
        if op.mode == "raised":
            base = half + embed * slope
            section = Polygon(
                [(-base, -embed), (base, -embed), (floor, op.depth_mm), (-floor, op.depth_mm)]
            )
        else:
            top = half + lip * slope
            section = Polygon(
                [(-top, lip), (top, lip), (floor, -op.depth_mm), (-floor, -op.depth_mm)]
            )
        angles = (
            [profile.angle_deg]
            if profile.pattern == "straight"
            else [profile.angle_deg, -profile.angle_deg]
        )
        sets = []
        count = 0
        for angle in angles:
            bars = _bars(surface, profile.area, profile.pitch_mm, angle, section)
            count += len(bars)
            sets.append(m3d.Manifold.batch_boolean([_manifold(b) for b in bars], m3d.OpType.Add))
        features = m3d.Manifold.batch_boolean(sets, m3d.OpType.Add)
        if op.mode == "raised":
            clip = _manifold(
                _area_prism(surface, profile.area, below=embed + 1.0, above=op.depth_mm + 1.0)
            )
            result = solid + (features ^ clip)
        else:
            clip = _manifold(
                _area_prism(surface, profile.area, below=op.depth_mm + 1.0, above=lip + 1.0)
            )
            result = solid - (features ^ clip)
    if result.is_empty():
        raise EditError("empty_result", "the detail removed the whole mesh")
    return _from_manifold(result), {
        "shape": profile.shape,
        "mode": op.mode,
        "cutters": count,
        "footprint_mm": corners,
    }


# --- driver ----------------------------------------------------------------------------------


def _validate(after: trimesh.Trimesh, was_watertight: bool, repairs: list[str]) -> None:
    if len(after.faces) == 0:
        raise EditError("empty_result", "the edit left no triangles")
    if len(after.faces) > MAX_FACES_AFTER:
        raise EditError("too_many_triangles", "the result is too large")
    if not np.isfinite(after.vertices).all():
        raise EditError("invalid_vertices", "the edit produced non-finite coordinates")
    if not was_watertight:
        return
    if after.is_watertight and after.is_winding_consistent:
        return
    # one bounded repair attempt, reported; never silently keep a broken solid
    after.merge_vertices()
    trimesh.repair.fix_normals(after)  # type: ignore[no-untyped-call]
    trimesh.repair.fix_winding(after)  # type: ignore[no-untyped-call]
    if after.is_watertight:
        repairs.append("normals and winding were re-oriented to restore a watertight solid")
        return
    closed, remaining = mesh_repair.close_holes(after)
    if closed:
        repairs.append(f"{closed} hole(s) were closed")
    if not after.is_watertight:
        raise EditError(
            "broke_watertight",
            "the edit would leave the model with open or non-manifold edges; "
            "it was not applied (try a smaller amount or a different selection)",
            remaining_loops=remaining,
        )


def edit_mesh(mesh: trimesh.Trimesh, request: EditRequest, output: Path | None) -> EditReport:
    """Apply the operations in order and (unless previewing) write the result as binary STL."""
    source_faces = len(mesh.faces)
    if request.expected_faces is not None and request.expected_faces != source_faces:
        return EditReport(
            ok=False,
            code="stale_selection",
            message=(
                f"the selection was made on a mesh of {request.expected_faces} triangles but this "
                f"one has {source_faces}; reopen the model and select again"
            ),
        )
    work = mesh.copy()
    work.merge_vertices()
    work.update_faces(work.nondegenerate_faces())
    work.remove_unreferenced_vertices()
    # Deleting without filling is a request for an open mesh; everything else must keep a solid.
    leaves_open = any(isinstance(op, DeleteFacesOp) and not op.fill for op in request.operations)
    was_watertight = bool(work.is_watertight) and not leaves_open
    before = _stats(work)
    report = EditReport(ok=True, before=before)
    preview = Preview() if request.preview else None
    for index, op in enumerate(request.operations):
        try:
            detail = _apply(work, op, request, report.warnings, preview)
        except EditError as exc:
            report.ok = False
            report.code, report.message = exc.code, exc.message
            report.details = exc.details
            report.failed_operation = index
            return report
        work = detail.pop("_mesh", work)
        report.applied.append(Applied(op=op.op, detail=detail))
    if preview is not None:
        report.preview = preview
        report.after = before
        return report
    try:
        _validate(work, was_watertight, report.repairs)
    except EditError as exc:
        report.ok = False
        report.code, report.message, report.details = exc.code, exc.message, exc.details
        return report
    report.after = _stats(work)
    if output is not None:
        exported = work.export(file_type="stl")
        output.write_bytes(exported.encode() if isinstance(exported, str) else bytes(exported))
        report.output_path = str(output)
    return report


def _apply(
    mesh: trimesh.Trimesh,
    op: Any,
    request: EditRequest,
    warnings: list[str],
    preview: Preview | None,
) -> dict[str, Any]:
    """Run one operation. Returns its report detail; a replaced mesh rides along as `_mesh`."""
    if isinstance(op, DetailOp):
        replaced, detail = _detail(mesh, op, request.tolerance_mm, preview)
        if preview is None:
            detail["_mesh"] = replaced
        return detail
    if preview is not None:
        return {"preview": True}  # selection edits have nothing to draw before they are applied
    if isinstance(op, BevelEdgesOp):
        replaced, detail = _bevel(mesh, _Locator(mesh), op, warnings)
        detail["_mesh"] = replaced
        return detail
    return _apply_selection_op(mesh, op, warnings)


def _apply_selection_op(mesh: trimesh.Trimesh, op: Any, warnings: list[str]) -> dict[str, Any]:
    loc = _Locator(mesh)
    if isinstance(op, MoveOp):
        return _move(mesh, loc, op)
    if isinstance(op, ScaleOp):
        return _scale(mesh, loc, op)
    if isinstance(op, RotateOp):
        return _rotate_selection(mesh, loc, op)
    if isinstance(op, ExtrudeOp):
        return _extrude(mesh, loc, op)
    if isinstance(op, InsetOp):
        return _inset(mesh, loc, op)
    if isinstance(op, DeleteFacesOp):
        return _delete_faces(mesh, loc, op, warnings)
    raise EditError("unknown_operation", f"unsupported operation {type(op).__name__}")


# --- file level ------------------------------------------------------------------------------


def _load(source: Path, source_format: str) -> trimesh.Trimesh | None:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        skip_materials=True,
        process=False,
    )
    mesh = as_single_mesh(loaded)
    return None if mesh is None else to_platform_axes(mesh.copy(), source_format)


def edit_file(
    source: Path, source_format: str, request: EditRequest, output: Path | None
) -> EditReport:
    mesh = _load(source, source_format)
    if mesh is None or mesh.is_empty:
        return EditReport(ok=False, code="no_mesh", message="the file has no mesh")
    return edit_mesh(mesh, request, output)


def run_in_sandbox(
    source: Path,
    source_format: str,
    request: EditRequest,
    output: Path | None,
    limits: Any | None = None,
) -> EditReport:
    """Edit in the sandboxed child, like every other operation on an uploaded mesh."""
    from worker import sandbox

    chosen = limits or sandbox.DEFAULT_LIMITS
    outcome = sandbox.run(
        "worker.meshedit",
        [source_format, str(source), str(output or ""), request.model_dump_json()],
        input_path=source,
        limits=chosen,
    )
    if not outcome.ok:
        assert outcome.failure is not None
        return EditReport(
            ok=False, code=f"sandbox_{outcome.failure.value}", message=outcome.message
        )
    return EditReport.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: meshedit <fmt> <source> <output|""> <request-json>
    import sys

    fmt, path, out, payload = sys.argv[1:5]
    try:
        result = edit_file(
            Path(path), fmt, EditRequest.model_validate_json(payload), Path(out) if out else None
        )
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        failure = {"ok": False, "code": "crashed", "message": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(failure))
        sys.exit(1)
