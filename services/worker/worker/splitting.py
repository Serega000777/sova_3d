"""Cut a model into printable parts (F-081, T-141).

A statuette taller than the bed, a bracket wider than it, a figure that would need a forest
of supports: cut it with planes and get parts that print. Every part is watertight with a
flat cut face (the booleans are manifold's: exact, no slivers); each cut gets dowel holes on
both sides so the parts go back together aligned, with the dowels as small parts of their
own; the parts are laid out on the bed cut-face-down. A mesh that is not a closed volume is
repaired first and refused only when the repair does not make it one — the user is told
which.

Everything here runs in the sandbox child like every other operation on an uploaded mesh.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field, model_validator
from scipy import ndimage

from worker.importers.common import as_single_mesh
from worker.repair import RepairReport, repair_mesh

Axis = Literal["x", "y", "z"]
AXIS_INDEX: dict[str, int] = {"x": 0, "y": 1, "z": 2}
MIN_PART_VOLUME_MM3 = 1.0  # a sliver thinner than this is a numerical accident, not a part
MIN_CAP_AREA_MM2 = 60.0  # below this a cut face has no room for a dowel
DOWEL_WALL_MM = 1.5  # material left around a dowel hole, radially and at the bottom
MAX_DOWELS_PER_CUT = 2
RASTER_CELLS = 400  # the cut face is rasterised on a grid this wide for the dowel spots
MAX_PARTS = 24


# --- request ------------------------------------------------------------------------------


class CutPlane(BaseModel):
    """A plane through the model: on an axis at an absolute coordinate or a fraction of the
    extent, or anywhere by point and normal."""

    axis: Axis | None = None
    offset_mm: float | None = None
    fraction: float | None = Field(default=None, gt=0.0, lt=1.0)
    point_mm: list[float] | None = Field(default=None, min_length=3, max_length=3)
    normal: list[float] | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def _one_form(self) -> CutPlane:
        placed = self.offset_mm is not None or self.fraction is not None
        by_axis = self.axis is not None and placed
        free = self.point_mm is not None and self.normal is not None
        if by_axis == free:
            raise ValueError("a plane is axis + offset_mm|fraction, or point_mm + normal")
        if free and float(np.linalg.norm(np.asarray(self.normal, dtype=float))) < 1e-9:
            raise ValueError("normal must not be zero")
        return self


class Connectors(BaseModel):
    kind: Literal["none", "dowel"] = "dowel"
    diameter_mm: float = Field(default=5.0, ge=1.5, le=20.0)
    length_mm: float = Field(default=12.0, ge=4.0, le=60.0)
    clearance_mm: float = Field(default=0.25, ge=0.0, le=1.0)


class Bed(BaseModel):
    x_mm: float = Field(gt=0)
    y_mm: float = Field(gt=0)
    z_mm: float = Field(gt=0)


class SplitRequest(BaseModel):
    planes: list[CutPlane] = Field(default_factory=list, max_length=8)
    # N equal parts along an axis (the longest extent when unset) — what "cut it in three" means
    parts: int | None = Field(default=None, ge=2, le=12)
    axis: Axis | None = None
    # cut until every part fits this bed, keeping `margin_mm` free on each side
    bed: Bed | None = None
    margin_mm: float = Field(default=5.0, ge=0.0, le=50.0)
    connectors: Connectors = Field(default_factory=Connectors)
    gap_mm: float = Field(default=8.0, ge=0.0, le=50.0)  # between parts on the plate
    repair: bool = True  # close holes and fix normals first when the mesh is not a volume

    @model_validator(mode="after")
    def _something_to_do(self) -> SplitRequest:
        if not self.planes and self.parts is None and self.bed is None:
            raise ValueError("give planes, a number of parts, or a bed to fit")
        return self


# --- results ------------------------------------------------------------------------------


class ResolvedPlane(BaseModel):
    origin_mm: list[float]
    normal: list[float]
    axis: Axis | None = None
    source: Literal["given", "equal_parts", "bed"]


class PartReport(BaseModel):
    name: str
    file: str
    faces: int
    volume_mm3: float
    extents_mm: list[float]  # as printed: cut face down, min corner at the origin
    cut_faces: int
    base_cut_area_mm2: float | None = None
    dowel_holes: int = 0
    fits_bed: bool | None = None
    # where the part sits on the plate: translation from its own origin to the layout
    plate_offset_mm: list[float]


class DowelReport(BaseModel):
    name: str
    file: str
    diameter_mm: float
    length_mm: float
    plate_offset_mm: list[float]


class SplitReport(BaseModel):
    ok: bool
    message: str = ""
    code: str | None = None
    planes: list[ResolvedPlane] = Field(default_factory=list)
    parts: list[PartReport] = Field(default_factory=list)
    dowels: list[DowelReport] = Field(default_factory=list)
    layout_file: str | None = None
    layout_extents_mm: list[float] | None = None
    repaired: RepairReport | None = None
    warnings: list[str] = Field(default_factory=list)
    input_volume_mm3: float | None = None


# --- planes -------------------------------------------------------------------------------


def _unit(vector: Any) -> np.ndarray:
    arr = np.asarray(vector, dtype=float)
    return arr / np.linalg.norm(arr)


def resolve_planes(mesh: trimesh.Trimesh, request: SplitRequest) -> list[ResolvedPlane]:
    lo, hi = np.asarray(mesh.bounds, dtype=float)
    extents = hi - lo
    planes: list[ResolvedPlane] = []

    for plane in request.planes:
        if plane.axis is not None:
            index = AXIS_INDEX[plane.axis]
            coordinate = (
                plane.offset_mm
                if plane.offset_mm is not None
                else lo[index] + extents[index] * float(plane.fraction or 0.5)
            )
            origin = (lo + hi) / 2
            origin[index] = coordinate
            normal = np.zeros(3)
            normal[index] = 1.0
            planes.append(
                ResolvedPlane(
                    origin_mm=origin.tolist(),
                    normal=normal.tolist(),
                    axis=plane.axis,
                    source="given",
                )
            )
        else:
            planes.append(
                ResolvedPlane(
                    origin_mm=[float(v) for v in plane.point_mm or []],
                    normal=_unit(plane.normal).tolist(),
                    source="given",
                )
            )

    if request.parts is not None:
        axis = request.axis or "xyz"[int(np.argmax(extents))]
        index = AXIS_INDEX[axis]
        for k in range(1, request.parts):
            origin = (lo + hi) / 2
            origin[index] = lo[index] + extents[index] * k / request.parts
            normal = np.zeros(3)
            normal[index] = 1.0
            planes.append(
                ResolvedPlane(
                    origin_mm=origin.tolist(),
                    normal=normal.tolist(),
                    axis=axis,
                    source="equal_parts",
                )
            )

    if request.bed is not None:
        room = [
            request.bed.x_mm - 2 * request.margin_mm,
            request.bed.y_mm - 2 * request.margin_mm,
            request.bed.z_mm - 2 * request.margin_mm,
        ]
        for index, axis in enumerate("xyz"):
            if room[index] <= 0 or extents[index] <= room[index]:
                continue
            count = math.ceil(extents[index] / room[index])
            for k in range(1, count):
                origin = (lo + hi) / 2
                origin[index] = lo[index] + extents[index] * k / count
                normal = np.zeros(3)
                normal[index] = 1.0
                planes.append(
                    ResolvedPlane(
                        origin_mm=origin.tolist(),
                        normal=normal.tolist(),
                        axis=axis,
                        source="bed",
                    )
                )
    return planes


# --- cutting ------------------------------------------------------------------------------


def _halfspace(origin: np.ndarray, normal: np.ndarray, reach: float) -> trimesh.Trimesh:
    """A box whose top face lies on the plane: intersecting with it keeps the side the normal
    points away from."""
    box: trimesh.Trimesh = trimesh.creation.box(extents=(reach, reach, reach))
    transform = trimesh.geometry.align_vectors([0.0, 0.0, 1.0], normal)
    box.apply_transform(transform)
    box.apply_translation(origin - normal * (reach / 2))
    return box


def _boolean(kind: str, a: trimesh.Trimesh, b: trimesh.Trimesh) -> trimesh.Trimesh:
    op = trimesh.boolean.intersection if kind == "intersection" else trimesh.boolean.difference
    result = op([a, b], engine="manifold")
    if not isinstance(result, trimesh.Trimesh):
        return trimesh.Trimesh()
    return result


class _Piece:
    """A part in progress: its mesh and which planes bound it (index, side)."""

    def __init__(self, mesh: trimesh.Trimesh, cuts: list[tuple[int, int]]) -> None:
        self.mesh = mesh
        self.cuts = cuts
        self.dowel_holes = 0


Pair = tuple[int, "_Piece", "_Piece"]  # plane index, the piece below it, the piece above


def cut(mesh: trimesh.Trimesh, planes: list[ResolvedPlane]) -> tuple[list[_Piece], list[Pair]]:
    """Split by every plane in turn. Returns the pieces and, per plane, the (below, above)
    pairs that came out of one piece — where a dowel belongs."""
    reach = float(np.linalg.norm(mesh.extents)) * 4 + 10
    pieces = [_Piece(mesh, [])]
    pairs: list[Pair] = []
    for index, plane in enumerate(planes):
        origin = np.asarray(plane.origin_mm, dtype=float)
        normal = np.asarray(plane.normal, dtype=float)
        below_box = _halfspace(origin, normal, reach)
        above_box = _halfspace(origin, -normal, reach)
        next_pieces: list[_Piece] = []
        for piece in pieces:
            below = _boolean("intersection", piece.mesh, below_box)
            above = _boolean("intersection", piece.mesh, above_box)
            has_below = not below.is_empty and abs(float(below.volume)) > MIN_PART_VOLUME_MM3
            has_above = not above.is_empty and abs(float(above.volume)) > MIN_PART_VOLUME_MM3
            if has_below and has_above:
                lower = _Piece(below, [*piece.cuts, (index, -1)])
                upper = _Piece(above, [*piece.cuts, (index, +1)])
                next_pieces += [lower, upper]
                pairs.append((index, lower, upper))
            else:
                next_pieces.append(piece)  # the plane missed this piece
        pieces = next_pieces
        if len(pieces) > MAX_PARTS:
            raise ValueError(f"more than {MAX_PARTS} parts — use fewer planes")
    return pieces, pairs


# --- dowels -------------------------------------------------------------------------------


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(normal, helper))
    v = np.cross(normal, u)
    return u, v


def cap_faces(mesh: trimesh.Trimesh, origin: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Faces lying on the plane with their outward normal along it: the cut face."""
    normals = np.asarray(mesh.face_normals, dtype=float)
    centroids = np.asarray(mesh.triangles_center, dtype=float)
    on_plane = np.abs((centroids - origin) @ normal) < 1e-3
    facing = normals @ normal > 0.999
    indices: np.ndarray = np.where(on_plane & facing)[0]
    return indices


def dowel_spots(
    mesh: trimesh.Trimesh,
    origin: np.ndarray,
    normal: np.ndarray,
    *,
    radius_mm: float,
    count: int,
) -> tuple[list[np.ndarray], float]:
    """Points on the cut face with the most material around them (max inscribed circle),
    at most `count`, each at least 4 radii from the others. Also the cut face area."""
    faces = cap_faces(mesh, origin, normal)
    if len(faces) == 0:
        return [], 0.0
    area = float(np.asarray(mesh.area_faces, dtype=float)[faces].sum())
    u, v = _plane_basis(normal)
    triangles = np.asarray(mesh.triangles, dtype=float)[faces]  # (n, 3, 3)
    flat = triangles - origin
    uv = np.stack([flat @ u, flat @ v], axis=-1)  # (n, 3, 2)
    lo = uv.reshape(-1, 2).min(axis=0)
    hi = uv.reshape(-1, 2).max(axis=0)
    span = float(max(hi - lo))
    if span <= 0:
        return [], area
    res = max(span / RASTER_CELLS, 0.25)
    width = int(math.ceil((hi[0] - lo[0]) / res)) + 3
    height = int(math.ceil((hi[1] - lo[1]) / res)) + 3
    mask = np.zeros((height, width), dtype=bool)
    grid_origin = lo - res  # one cell of padding so the border is outside

    for tri in uv:
        (x0, y0), (x1, y1), (x2, y2) = tri
        cx0 = int((min(x0, x1, x2) - grid_origin[0]) / res)
        cx1 = int((max(x0, x1, x2) - grid_origin[0]) / res) + 1
        cy0 = int((min(y0, y1, y2) - grid_origin[1]) / res)
        cy1 = int((max(y0, y1, y2) - grid_origin[1]) / res) + 1
        xs = grid_origin[0] + (np.arange(cx0, cx1 + 1) + 0.5) * res
        ys = grid_origin[1] + (np.arange(cy0, cy1 + 1) + 0.5) * res
        px, py = np.meshgrid(xs, ys)
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-12:
            continue
        a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
        b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
        c = 1 - a - b
        inside = (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
        ys_idx = np.clip(np.arange(cy0, cy1 + 1), 0, height - 1)
        xs_idx = np.clip(np.arange(cx0, cx1 + 1), 0, width - 1)
        sub = mask[np.ix_(ys_idx, xs_idx)]
        mask[np.ix_(ys_idx, xs_idx)] = sub | inside

    distance = ndimage.distance_transform_edt(mask) * res
    spots: list[np.ndarray] = []
    needed = radius_mm + DOWEL_WALL_MM
    for _ in range(count):
        flat_index = int(np.argmax(distance))
        best = float(distance.flat[flat_index])
        if best < needed:
            break
        row, col = divmod(flat_index, width)
        point_uv = grid_origin + (np.array([col, row]) + 0.5) * res
        spots.append(origin + u * point_uv[0] + v * point_uv[1])
        # keep the next dowel well away from this one
        rows, cols = np.ogrid[:height, :width]
        too_close = (rows - row) ** 2 + (cols - col) ** 2 < (4 * radius_mm / res) ** 2
        distance[too_close] = 0.0
    return spots, area


def _depth_along(mesh: trimesh.Trimesh, point: np.ndarray, direction: np.ndarray) -> float:
    """How far the part extends from `point` along `direction` before its surface ends."""
    start = point + direction * 0.05
    locations, _, _ = mesh.ray.intersects_location(
        ray_origins=start[None, :], ray_directions=direction[None, :]
    )
    if len(locations) == 0:
        return 0.0
    distances = np.linalg.norm(np.asarray(locations) - start, axis=1)
    return float(distances.min()) + 0.05


def add_dowels(
    pairs: list[Pair], planes: list[ResolvedPlane], connectors: Connectors
) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[str], float]:
    """Dowel holes on both sides of every cut; returns (point, normal) per dowel placed, the
    warnings, and the material the holes removed."""
    placed: list[tuple[np.ndarray, np.ndarray]] = []
    warnings: list[str] = []
    removed = 0.0
    hole_radius = connectors.diameter_mm / 2 + connectors.clearance_mm
    half = connectors.length_mm / 2
    for index, lower, upper in pairs:
        plane = planes[index]
        origin = np.asarray(plane.origin_mm, dtype=float)
        normal = np.asarray(plane.normal, dtype=float)
        spots, area = dowel_spots(
            lower.mesh, origin, normal, radius_mm=hole_radius, count=MAX_DOWELS_PER_CUT
        )
        if area < MIN_CAP_AREA_MM2 or not spots:
            warnings.append(f"cut {index + 1}: the cut face is too small for a dowel")
            continue
        for spot in spots:
            depth_down = _depth_along(lower.mesh, spot, -normal)
            depth_up = _depth_along(upper.mesh, spot, normal)
            if min(depth_down, depth_up) < half + DOWEL_WALL_MM:
                warnings.append(f"cut {index + 1}: too thin at the dowel spot, left without")
                continue
            hole = trimesh.creation.cylinder(
                radius=hole_radius, height=connectors.length_mm + 2 * connectors.clearance_mm
            )
            hole.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], normal))
            hole.apply_translation(spot)
            before = abs(float(lower.mesh.volume)) + abs(float(upper.mesh.volume))
            lower.mesh = _boolean("difference", lower.mesh, hole)
            upper.mesh = _boolean("difference", upper.mesh, hole)
            removed += before - abs(float(lower.mesh.volume)) - abs(float(upper.mesh.volume))
            lower.dowel_holes += 1
            upper.dowel_holes += 1
            placed.append((spot, normal))
    return placed, warnings, removed


# --- orientation and layout -----------------------------------------------------------------


def _cap_area(mesh: trimesh.Trimesh, origin: np.ndarray, outward: np.ndarray) -> float:
    faces = cap_faces(mesh, origin, outward)
    return float(np.asarray(mesh.area_faces, dtype=float)[faces].sum()) if len(faces) else 0.0


def _flat_bottom_area(mesh: trimesh.Trimesh) -> float:
    """The part's own flat underside, if it has one (a statue's base beats a small cut)."""
    floor = np.asarray(mesh.bounds[0], dtype=float)
    return _cap_area(mesh, floor, np.array([0.0, 0.0, -1.0]))


def orient_cut_face_down(piece: _Piece, planes: list[ResolvedPlane]) -> float | None:
    """Rotate the part so its largest flat face — a cut face or its own base — is the
    underside, and put it at the origin."""
    best: tuple[float, np.ndarray] = (_flat_bottom_area(piece.mesh), np.array([0.0, 0.0, -1.0]))
    for index, side in piece.cuts:
        origin = np.asarray(planes[index].origin_mm, dtype=float)
        # the piece below the plane (side -1) has its cut face pointing along the normal
        outward = np.asarray(planes[index].normal, dtype=float) * -side
        area = _cap_area(piece.mesh, origin, outward)
        if area > best[0]:
            best = (area, outward)
    if best[0] > 0:
        piece.mesh.apply_transform(trimesh.geometry.align_vectors(best[1], [0.0, 0.0, -1.0]))
    piece.mesh.apply_translation(-np.asarray(piece.mesh.bounds[0], dtype=float))
    return best[0] if best[0] > 0 else None


def _fits(extents: np.ndarray, bed: Bed | None, margin: float) -> bool | None:
    if bed is None:
        return None
    room_x, room_y, room_z = bed.x_mm - 2 * margin, bed.y_mm - 2 * margin, bed.z_mm - 2 * margin
    x, y, z = (float(v) for v in extents)
    return z <= room_z and ((x <= room_x and y <= room_y) or (y <= room_x and x <= room_y))


def layout(
    meshes: list[trimesh.Trimesh], *, gap: float, row_width: float | None
) -> list[np.ndarray]:
    """Shelf packing on the plate: biggest footprints first, rows wrap at `row_width`."""
    order = sorted(
        range(len(meshes)),
        key=lambda i: -float(meshes[i].extents[0] * meshes[i].extents[1]),
    )
    offsets: list[np.ndarray] = [np.zeros(3) for _ in meshes]
    x = y = row_height = 0.0
    for i in order:
        w, d = float(meshes[i].extents[0]), float(meshes[i].extents[1])
        if row_width is not None and x > 0 and x + w > row_width:
            x, y, row_height = 0.0, y + row_height + gap, 0.0
        offsets[i] = np.array([x, y, 0.0])
        x += w + gap
        row_height = max(row_height, d)
    return offsets


# --- the whole thing ----------------------------------------------------------------------


def split_mesh(mesh: trimesh.Trimesh, request: SplitRequest, out_dir: Path) -> SplitReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh = mesh.copy()
    mesh.merge_vertices()
    report = SplitReport(ok=True)

    if not (mesh.is_watertight and mesh.is_volume):
        if not request.repair:
            return SplitReport(
                ok=False,
                code="not_a_volume",
                message="the model is not a closed volume; repair it first or allow repair",
            )
        report.repaired = repair_mesh(mesh)
        if not (mesh.is_watertight and mesh.is_volume):
            return SplitReport(
                ok=False,
                code="not_a_volume",
                message="the model is not a closed volume even after repair — "
                "run Repair and look at what it could not close",
                repaired=report.repaired,
            )
    report.input_volume_mm3 = round(float(mesh.volume), 3)

    planes = resolve_planes(mesh, request)
    if not planes:
        return SplitReport(ok=False, code="nothing_to_cut", message="the model already fits")
    report.planes = planes
    try:
        pieces, pairs = cut(mesh, planes)
    except ValueError as exc:
        return SplitReport(ok=False, code="too_many_parts", message=str(exc), planes=planes)
    if len(pieces) < 2:
        return SplitReport(
            ok=False,
            code="plane_misses",
            message="no plane passes through the model",
            planes=planes,
        )

    dowels: list[tuple[np.ndarray, np.ndarray]] = []
    removed = 0.0
    if request.connectors.kind == "dowel":
        dowels, warnings, removed = add_dowels(pairs, planes, request.connectors)
        report.warnings += warnings

    # orient every part cut-face-down, then the dowels standing up
    base_areas = [orient_cut_face_down(piece, planes) for piece in pieces]
    part_meshes = [piece.mesh for piece in pieces]
    dowel_meshes: list[trimesh.Trimesh] = []
    for _ in dowels:
        pin = trimesh.creation.cylinder(
            radius=request.connectors.diameter_mm / 2, height=request.connectors.length_mm
        )
        pin.apply_translation(-np.asarray(pin.bounds[0], dtype=float))
        dowel_meshes.append(pin)

    everything = part_meshes + dowel_meshes
    row_width = request.bed.x_mm - 2 * request.margin_mm if request.bed else None
    offsets = layout(everything, gap=request.gap_mm, row_width=row_width)

    for index, (piece, base_area) in enumerate(zip(pieces, base_areas, strict=True)):
        name = f"part_{index + 1:02d}"
        file = f"{name}.stl"
        (out_dir / file).write_bytes(_as_bytes(piece.mesh.export(file_type="stl")))
        extents = np.asarray(piece.mesh.extents, dtype=float)
        report.parts.append(
            PartReport(
                name=name,
                file=file,
                faces=int(len(piece.mesh.faces)),
                volume_mm3=round(float(piece.mesh.volume), 3),
                extents_mm=[round(float(v), 3) for v in extents],
                cut_faces=len(piece.cuts),
                base_cut_area_mm2=None if base_area is None else round(base_area, 2),
                dowel_holes=piece.dowel_holes,
                fits_bed=_fits(extents, request.bed, request.margin_mm),
                plate_offset_mm=[round(float(v), 3) for v in offsets[index]],
            )
        )
    for index, pin in enumerate(dowel_meshes):
        name = f"dowel_{index + 1:02d}"
        file = f"{name}.stl"
        (out_dir / file).write_bytes(_as_bytes(pin.export(file_type="stl")))
        report.dowels.append(
            DowelReport(
                name=name,
                file=file,
                diameter_mm=request.connectors.diameter_mm,
                length_mm=request.connectors.length_mm,
                plate_offset_mm=[round(float(v), 3) for v in offsets[len(pieces) + index]],
            )
        )

    placed = []
    for item, offset in zip(everything, offsets, strict=True):
        moved = item.copy()
        moved.apply_translation(offset)
        placed.append(moved)
    plate = trimesh.util.concatenate(placed)
    assert isinstance(plate, trimesh.Trimesh)
    (out_dir / "layout.stl").write_bytes(_as_bytes(plate.export(file_type="stl")))
    report.layout_file = "layout.stl"
    report.layout_extents_mm = [round(float(v), 3) for v in np.asarray(plate.extents)]

    total = sum(p.volume_mm3 for p in report.parts) + removed
    original = report.input_volume_mm3 or 0.0
    if original and abs(total - original) > 0.01 * original:
        report.warnings.append(
            f"the parts hold {total:.0f} mm³ of the original {report.input_volume_mm3:.0f} mm³"
        )
    if request.bed is not None and any(p.fits_bed is False for p in report.parts):
        report.warnings.append("some parts still do not fit the bed: add a plane or a margin")
    return report


def _as_bytes(exported: object) -> bytes:
    if isinstance(exported, str):
        return exported.encode()
    if isinstance(exported, bytes | bytearray):
        return bytes(exported)
    raise TypeError(f"unexpected export payload {type(exported).__name__}")


def _load(source: Path, source_format: str) -> trimesh.Trimesh | None:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        skip_materials=True,
        process=False,
    )
    return as_single_mesh(loaded)


def split_file(
    source: Path, source_format: str, request: SplitRequest, out_dir: Path
) -> SplitReport:
    mesh = _load(source, source_format)
    if mesh is None or mesh.is_empty:
        return SplitReport(ok=False, code="no_mesh", message="the file has no mesh")
    return split_mesh(mesh, request, out_dir)


def run_in_sandbox(
    source: Path,
    source_format: str,
    request: SplitRequest,
    out_dir: Path,
    limits: Any | None = None,
) -> SplitReport:
    """Cut in the sandboxed child, like every other operation on an uploaded mesh."""
    from worker import sandbox

    chosen = limits or sandbox.DEFAULT_LIMITS
    outcome = sandbox.run(
        "worker.splitting",
        [source_format, str(source), str(out_dir), request.model_dump_json()],
        input_path=source,
        limits=chosen,
    )
    if not outcome.ok:
        assert outcome.failure is not None
        return SplitReport(
            ok=False, code=f"sandbox_{outcome.failure.value}", message=outcome.message
        )
    return SplitReport.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: splitting <fmt> <source> <out_dir> <request-json>
    import sys

    fmt, path, out, payload = sys.argv[1:5]
    try:
        result = split_file(Path(path), fmt, SplitRequest.model_validate_json(payload), Path(out))
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        failure = {"ok": False, "code": "crashed", "message": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(failure))
        sys.exit(1)
