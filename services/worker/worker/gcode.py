"""Real slicing (F-054, second stage): perimeters, infill and machine G-code.

`slicing.py` only samples cross-section contours for a viewer. This module walks every
layer of a watertight mesh, offsets each layer's polygons (trimesh + shapely handle the
holes) into `wall_count` perimeter loops, fills what is left at the requested density —
either straight lines (alternating 0/90 degrees per layer) or a real hexagonal tiling
(`infill_pattern="honeycomb"`; a true honeycomb, not three crossed line families, which
tile triangles instead) — and writes the whole toolpath as G-code a Marlin-family
firmware can run: absolute XY, relative extrusion (M83), one retract per travel move.
Every loop starts at its rearmost corner so the seams stack into one line at the back,
and infill/support paths are printed nearest-first to cut travel.

Supports are straight columns under faces steeper than the printer's overhang limit —
one column per grid cell of the bed, from the plate up to the lowest point that needs
holding up. Not tree supports; a single thin perimeter loop per layer, weak enough to
snap off by hand, the way a beginner-friendly default should be.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import shapely
import trimesh
from pydantic import BaseModel, Field
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from worker import sandbox
from worker.importers.common import as_single_mesh
from worker.printcheck import PrinterProfile
from worker.sandbox import SandboxLimits

SLICE_LIMITS = SandboxLimits(wall_seconds=600, max_output_bytes=64 * 1024 * 1024)
MAX_LAYERS = 10000

# Nearly universal for desktop FDM; not printer-specific enough yet to earn its own
# PrinterProfile field.
FILAMENT_DIAMETER_MM = 1.75

# Conservative desktop defaults, (nozzle_c, bed_c). Matches the material ids in
# app/engineering/knowledge.py's DENSITY_G_CM3 table on the API side.
PRINT_TEMPS_C: dict[str, tuple[float, float]] = {
    "pla": (200.0, 60.0),
    "petg": (235.0, 80.0),
    "abs": (245.0, 100.0),
    "tpu": (220.0, 50.0),
    "asa": (250.0, 100.0),
}

MAX_ORDERED_PATHS = 2000
SKIRT_GAP_MM = 5.0
SUPPORT_GRID_MM = 4.0
SUPPORT_WIDTH_MM = 1.6
# One empty layer between support and part, so the support snaps off instead of fusing on,
# and two dense layers right under the overhang so its underside prints on a floor.
SUPPORT_Z_GAP_LAYERS = 1
SUPPORT_INTERFACE_LAYERS = 2
CONTACT_EPS_MM = 0.05


DEFAULT_RETRACTION_MM = 1.2
MIN_NOZZLE_C = 150.0


class PrintTuning(BaseModel):
    """F-056: what earlier prints of this material on this printer taught; defaults = nothing."""

    nozzle_offset_c: float = Field(default=0.0, ge=-20.0, le=20.0)
    bed_offset_c: float = Field(default=0.0, ge=-20.0, le=20.0)
    retraction_mm: float = Field(default=DEFAULT_RETRACTION_MM, ge=0.0, le=8.0)
    flow_pct: float = Field(default=100.0, ge=80.0, le=120.0)
    # loops around the first layer that hold its corners down (0 = none, a skirt instead)
    brim_mm: float = Field(default=0.0, ge=0.0, le=15.0)
    # the first layer's outlines pulled in further: it squashes out wider than the rest
    elephant_foot_mm: float = Field(default=0.0, ge=0.0, le=0.5)
    first_layer_speed_pct: float = Field(default=100.0, ge=20.0, le=100.0)

    def changes(self) -> dict[str, float]:
        """Only what differs from an untuned print, for the header and the stats."""
        default = PrintTuning()
        return {
            name: float(getattr(self, name))
            for name in PrintTuning.model_fields
            if getattr(self, name) != getattr(default, name)
        }


class SliceSettings(BaseModel):
    material_id: str = "pla"
    infill_density_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    infill_pattern: Literal["lines", "honeycomb"] = "lines"
    wall_count: int = Field(default=2, ge=1, le=6)
    supports: bool = False
    skirt: bool = True
    tuning: PrintTuning = Field(default_factory=PrintTuning)


class SliceStats(BaseModel):
    total_layers: int
    filament_used_mm: float
    filament_used_g: float
    estimated_time_s: float
    support_columns: int
    # Non-printing head moves: what path ordering (_nearest_first) exists to cut.
    travel_mm: float = 0.0
    # The printer's measured calibration as applied to this toolpath (0 = none on file).
    xy_compensation_mm: float = 0.0
    shrinkage_pct: float = 0.0
    flow_pct: float = 100.0
    # F-056: the learned corrections this G-code carries (empty = none)
    tuning: dict[str, float] = Field(default_factory=dict)
    brim_loops: int = 0
    gcode_file: str
    gcode_sha256: str
    gcode_bytes: int


def _as_polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [p for p in geom.geoms if not p.is_empty]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def _as_lines(geom: BaseGeometry) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [line for line in geom.geoms if line.length > 0]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, LineString) and g.length > 0]
    return []


def _polygons_at(mesh: trimesh.Trimesh, z: float) -> list[Polygon]:
    section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if section is None:
        return []
    # An explicit identity keeps the mesh's own XY. Left to itself, to_2D() fits a frame
    # centred on each section's points — every layer lands at its own centroid, so a post
    # on one side of a slab would print over the slab's middle, and supports (placed in
    # the mesh frame) under the wrong spot.
    planar, _ = section.to_2D(to_2D=np.eye(4))
    return [p for p in planar.polygons_full if p.is_valid and p.area > 1e-6]


def _perimeter_rings(
    polygon: Polygon, nozzle_mm: float, wall_count: int
) -> tuple[list[list[tuple[float, float]]], list[Polygon]]:
    """Outer-to-inner perimeter loops, and what is left over for infill."""
    rings: list[list[tuple[float, float]]] = []
    remaining: BaseGeometry = polygon
    for pass_index in range(wall_count):
        offset = nozzle_mm / 2 + pass_index * nozzle_mm
        shrunk = polygon.buffer(-offset, join_style="mitre")
        parts = _as_polygons(shrunk)
        if not parts:
            remaining = shrunk
            break
        for part in parts:
            rings.append([(round(x, 3), round(y, 3)) for x, y in part.exterior.coords])
            for interior in part.interiors:
                rings.append([(round(x, 3), round(y, 3)) for x, y in interior.coords])
        remaining = shrunk
    infill_area = (
        remaining.buffer(-nozzle_mm / 2, join_style="mitre")
        if not remaining.is_empty
        else remaining
    )
    return rings, _as_polygons(infill_area)


def _infill_lines(
    polygons: list[Polygon], spacing_mm: float, angle_deg: float
) -> list[list[tuple[float, float]]]:
    if not polygons or spacing_mm <= 0:
        return []
    lines: list[list[tuple[float, float]]] = []
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    for poly in polygons:
        minx, miny, maxx, maxy = poly.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        half_diag = math.hypot(maxx - minx, maxy - miny) / 2 + spacing_mm
        steps = int(2 * half_diag / spacing_mm) + 1
        for i in range(-steps, steps + 1):
            offset = i * spacing_mm
            px, py = cx - offset * sin_t, cy + offset * cos_t
            dx, dy = cos_t * half_diag, sin_t * half_diag
            probe = LineString([(px - dx, py - dy), (px + dx, py + dy)])
            for segment in _as_lines(probe.intersection(poly)):
                if segment.length > spacing_mm * 0.1:
                    lines.append([(round(x, 3), round(y, 3)) for x, y in segment.coords])
    return lines


def _hexagon_vertices(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    """A pointy-top hexagon; `size` is its centre-to-vertex radius."""
    return [
        (
            cx + size * math.cos(math.radians(60 * k - 30)),
            cy + size * math.sin(math.radians(60 * k - 30)),
        )
        for k in range(6)
    ]


HexEdge = tuple[tuple[float, float], tuple[float, float]]


def _hex_tiling_edges(
    minx: float, miny: float, maxx: float, maxy: float, cell_mm: float
) -> list[HexEdge]:
    """The unique edges of a hexagonal tiling covering the given bounds, unclipped.

    Every interior edge belongs to two neighbouring hexagons; a plain dict keyed by its
    (rounded, order-independent) endpoints dedupes that before any wall is printed twice
    — cheap, versus asking `shapely.unary_union` to discover the same exact-duplicate
    structure through general-purpose overlay noding, which is orders of magnitude
    slower over a whole tiling's worth of segments. Expensive enough on its own
    (thousands of trig calls) that a whole slice job builds it once from the mesh's XY
    bounds and clips it per layer (`_honeycomb_lines`'s `edges` argument), rather than
    rebuilding the same tiling for every one of a print's layers."""
    if cell_mm <= 0:
        return []
    size = cell_mm / math.sqrt(3)  # centre-to-vertex, so flat-to-flat width == cell_mm
    col_spacing = math.sqrt(3) * size
    row_spacing = 1.5 * size
    margin = size * 2
    edges: dict[HexEdge, HexEdge] = {}
    row = 0
    y = miny - margin
    while y <= maxy + margin:
        x_offset = col_spacing / 2 if row % 2 else 0.0
        x = minx - margin + x_offset
        while x <= maxx + margin:
            verts = _hexagon_vertices(x, y, size)
            for i in range(6):
                a, b = verts[i], verts[(i + 1) % 6]
                key_a, key_b = (round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4))
                edges[(key_a, key_b) if key_a < key_b else (key_b, key_a)] = (a, b)
            x += col_spacing
        y += row_spacing
        row += 1
    return list(edges.values())


def _hex_tiling_grid(
    minx: float, miny: float, maxx: float, maxy: float, cell_mm: float
) -> MultiLineString:
    return MultiLineString(
        [LineString([a, b]) for a, b in _hex_tiling_edges(minx, miny, maxx, maxy, cell_mm)]
    )


def _honeycomb_lines(
    polygons: list[Polygon], cell_mm: float, grid: MultiLineString | None = None
) -> list[list[tuple[float, float]]]:
    """A real hexagonal tiling (not three crossed line families, which would tile
    triangles instead), clipped to each polygon. Pass a precomputed `grid` (from
    `_hex_tiling_grid`, sized to the whole mesh) when slicing many layers — otherwise
    this builds one sized to just these polygons' own bounds. Either way, clipping is one
    GEOS call over the whole grid, not one Python-level call per tiny hex edge — at fine
    (high-density) cells the tiling is thousands of segments, and clipping each one
    individually is what actually blew the sandbox's wall-clock budget, not the tiling
    generation itself (which a print's layers already share)."""
    if not polygons or cell_mm <= 0:
        return []
    if grid is None:
        minx = min(p.bounds[0] for p in polygons)
        miny = min(p.bounds[1] for p in polygons)
        maxx = max(p.bounds[2] for p in polygons)
        maxy = max(p.bounds[3] for p in polygons)
        grid = _hex_tiling_grid(minx, miny, maxx, maxy, cell_mm)
    if grid.is_empty:
        return []
    lines: list[list[tuple[float, float]]] = []
    for poly in polygons:
        for piece in _as_lines(grid.intersection(poly)):
            if piece.length > cell_mm * 0.02:
                lines.append([(round(x, 3), round(y, 3)) for x, y in piece.coords])
    return lines


Path2 = list[tuple[float, float]]


def _seam_first(ring: Path2, anchor: tuple[float, float]) -> Path2:
    """Start a closed loop at its corner nearest the anchor. Where a loop starts and ends
    it leaves a small blob; with one anchor behind the part for every layer, the blobs
    stack into a single line at the back ("rear seam") instead of scarring the surface."""
    if len(ring) < 4 or ring[0] != ring[-1]:
        return ring
    body = ring[:-1]
    ax, ay = anchor
    start = min(range(len(body)), key=lambda i: (body[i][0] - ax) ** 2 + (body[i][1] - ay) ** 2)
    rotated = body[start:] + body[:start]
    return [*rotated, rotated[0]]


def _nearest_first(paths: list[Path2], start: tuple[float, float]) -> list[Path2]:
    """Greedy nearest-neighbour ordering: from where the nozzle is, print whichever
    remaining path begins or ends closest (reversed if its end is), then chase the next
    from where that one finished. Not an optimal tour — that is TSP — but it stops the head
    crossing the part between neighbouring segments. Past MAX_ORDERED_PATHS the O(n^2)
    search would cost more than it saves, so the generation order (already a sweep) stands.
    """
    if len(paths) < 2 or len(paths) > MAX_ORDERED_PATHS:
        return paths
    starts = np.asarray([p[0] for p in paths], dtype=float)
    ends = np.asarray([p[-1] for p in paths], dtype=float)
    pending = np.ones(len(paths), dtype=bool)
    x, y = start
    ordered: list[Path2] = []
    for _ in range(len(paths)):
        to_start = np.where(pending, (starts[:, 0] - x) ** 2 + (starts[:, 1] - y) ** 2, np.inf)
        to_end = np.where(pending, (ends[:, 0] - x) ** 2 + (ends[:, 1] - y) ** 2, np.inf)
        by_start, by_end = int(to_start.argmin()), int(to_end.argmin())
        if to_end[by_end] < to_start[by_start]:
            path, pending[by_end] = paths[by_end][::-1], False
        else:
            path, pending[by_start] = paths[by_start], False
        ordered.append(path)
        x, y = path[-1]
    return ordered


@dataclass(frozen=True, slots=True)
class SupportColumn:
    x: float
    y: float
    bottom: float  # what it stands on: the bed, or the part's own surface below
    top: float  # the overhang it holds up


@dataclass(frozen=True, slots=True)
class Supports:
    columns: list[SupportColumn]
    # the overhangs seen from above: support never prints outside it
    footprint: BaseGeometry | None = None


def _support_columns(
    mesh: trimesh.Trimesh, printer: PrinterProfile, spacing_mm: float = SUPPORT_GRID_MM
) -> Supports:
    """One straight column per grid cell under an overhang, in the mesh's own frame,
    standing on the first surface straight below it — the bed, or the part itself (a
    column started from the bed would print through any of the part in between)."""
    normals = np.asarray(mesh.face_normals)
    areas = np.asarray(mesh.area_faces)
    centroids = np.asarray(mesh.triangles_center)
    bed_z = float(mesh.bounds[0][2])
    down = -normals[:, 2]
    threshold = math.cos(math.radians(printer.max_overhang_deg))
    on_bed = centroids[:, 2] - bed_z <= CONTACT_EPS_MM
    unsupported = (down > threshold) & ~on_bed & (areas > 1e-6)
    if not unsupported.any():
        return Supports([])
    triangles = np.asarray(mesh.triangles)[unsupported][:, :, :2]
    footprint = unary_union([Polygon(t) for t in triangles if Polygon(t).area > 1e-9])
    # Grid points inside the overhangs' outline, not triangle centres: a CAD face is two
    # huge triangles, and one column per triangle would leave most of it hanging in air.
    minx, miny, maxx, maxy = footprint.bounds
    xs = np.arange(math.floor(minx / spacing_mm), math.ceil(maxx / spacing_mm) + 1) * spacing_mm
    ys = np.arange(math.floor(miny / spacing_mm), math.ceil(maxy / spacing_mm) + 1) * spacing_mm
    gx, gy = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(footprint, gx.ravel(), gy.ravel())
    points = list(zip(gx.ravel()[inside].tolist(), gy.ravel()[inside].tolist(), strict=True))
    # an overhang too small to hold a grid point still gets a column at its middle
    covered = shapely.MultiPoint(points) if points else None
    for part in _as_polygons(footprint):
        if covered is None or not part.intersects(covered):
            centre = part.representative_point()
            points.append((float(centre.x), float(centre.y)))
    if not points:
        return Supports([], footprint)
    above = float(mesh.bounds[1][2]) + 1.0
    origins = np.array([(x, y, above) for x, y in points], dtype=float)
    rays_down = np.tile((0.0, 0.0, -1.0), (len(points), 1))
    hits, rays, faces = mesh.ray.intersects_location(origins, rays_down, multiple_hits=True)
    per_ray: dict[int, list[tuple[float, bool]]] = {}
    for hit, ray, face in zip(hits, rays, faces, strict=True):
        per_ray.setdefault(int(ray), []).append((float(hit[2]), bool(unsupported[face])))
    columns: list[SupportColumn] = []
    for ray, found in per_ray.items():
        found.sort()
        for index, (z, overhang) in enumerate(found):
            if not overhang:
                continue
            below = [hz for hz, _ in found[:index] if hz < z - 1e-4]
            floor = max(below) if below else bed_z  # the next surface down, or the bed
            if z - floor > 2 * printer.layer_height_mm:
                x, y = points[ray]
                columns.append(SupportColumn(x, y, floor, z))
    return Supports(columns, footprint)


def _support_paths(
    supports: Supports,
    section_z: float,
    part: list[Polygon],
    printer: PrinterProfile,
    line_width: float,
    bed_z: float,
) -> tuple[list[Path2], list[Path2]]:
    """This layer's support: column outlines, and dense interface lines under an overhang.

    Nothing is printed within a layer of the part (above or below), nor where this layer's
    own cross-section already is.
    """
    gap = printer.layer_height_mm * SUPPORT_Z_GAP_LAYERS
    interface_from = printer.layer_height_mm * (SUPPORT_Z_GAP_LAYERS + SUPPORT_INTERFACE_LAYERS)
    keep_out = unary_union(part).buffer(line_width) if part else None
    outlines: list[Path2] = []
    interface: list[Polygon] = []
    for column in supports.columns:
        start = column.bottom + (gap if column.bottom > bed_z + CONTACT_EPS_MM else 0.0)
        if not start <= section_z <= column.top - gap:
            continue
        if section_z >= column.top - interface_from:
            half = SUPPORT_GRID_MM / 2
            cell: BaseGeometry = Polygon(
                [
                    (column.x - half, column.y - half),
                    (column.x + half, column.y - half),
                    (column.x + half, column.y + half),
                    (column.x - half, column.y + half),
                ]
            )
            if supports.footprint is not None:
                cell = cell.intersection(supports.footprint)
            if keep_out is not None:
                cell = cell.difference(keep_out)
            interface.extend(p for p in _as_polygons(cell) if p.area > line_width**2)
            continue
        square = _square(column.x, column.y, SUPPORT_WIDTH_MM)
        if keep_out is not None and keep_out.intersects(Polygon(square)):
            continue
        outlines.append(square)
    return outlines, _infill_lines(interface, line_width, 0.0)


def _square(cx: float, cy: float, side: float) -> list[tuple[float, float]]:
    h = side / 2
    return [
        (round(cx - h, 3), round(cy - h, 3)),
        (round(cx + h, 3), round(cy - h, 3)),
        (round(cx + h, 3), round(cy + h, 3)),
        (round(cx - h, 3), round(cy + h, 3)),
        (round(cx - h, 3), round(cy - h, 3)),
    ]


def _filament_area_mm2() -> float:
    r = FILAMENT_DIAMETER_MM / 2
    return math.pi * r * r


def _extrusion_mm(length_mm: float, printer: PrinterProfile, line_width_mm: float) -> float:
    bead_area = printer.layer_height_mm * line_width_mm
    return (length_mm * bead_area) / _filament_area_mm2()


class _Writer:
    """Assembles G-code lines and keeps a running filament/travel tally."""

    def __init__(
        self,
        printer: PrinterProfile,
        retraction_mm: float,
        retraction_speed_mm_s: float,
        flow: float = 1.0,
    ):
        self.lines: list[str] = []
        self.printer = printer
        self.flow = flow
        self.retraction_mm = retraction_mm
        self.retract_feed = retraction_speed_mm_s * 60
        self.travel_feed = printer.print_speed_mm_s * 60 * 2
        self.print_feed = printer.print_speed_mm_s * 60
        self.filament_mm = 0.0
        self.travel_mm = 0.0
        self.extruding = False
        self.x: float | None = None
        self.y: float | None = None

    def comment(self, text: str) -> None:
        self.lines.append(f"; {text}")

    def raw(self, text: str) -> None:
        self.lines.append(text)

    def set_z(self, z_mm: float) -> None:
        self.lines.append(f"G1 Z{z_mm:.3f} F600")

    def _travel_to(self, x: float, y: float) -> None:
        if self.extruding:
            self.lines.append(f"G1 E-{self.retraction_mm:.4f} F{self.retract_feed:.0f}")
            self.extruding = False
        if self.x is not None and self.y is not None:
            self.travel_mm += math.hypot(x - self.x, y - self.y)
        self.lines.append(f"G1 X{x:.3f} Y{y:.3f} F{self.travel_feed:.0f}")

    def loop(self, points: list[tuple[float, float]], line_width_mm: float) -> None:
        if len(points) < 2:
            return
        self._travel_to(*points[0])
        # Plain locals, not `self.x or x`: a coordinate of exactly 0.0 is falsy, and that
        # fallback used to zero the segment's length and silently drop it from the print.
        px, py = points[0]
        for x, y in points[1:]:
            length = math.hypot(x - px, y - py)
            if length <= 1e-6:
                continue
            if not self.extruding:
                self.lines.append(f"G1 E{self.retraction_mm:.4f} F{self.retract_feed:.0f}")
                self.extruding = True
            e = _extrusion_mm(length, self.printer, line_width_mm) * self.flow
            self.filament_mm += e
            self.lines.append(f"G1 X{x:.3f} Y{y:.3f} E{e:.5f} F{self.print_feed:.0f}")
            px, py = x, y
        self.x, self.y = px, py


def _compensated(polygons: list[Polygon], xy_compensation_mm: float) -> list[Polygon]:
    """Pull every outline in by the printer's measured line fatness (F-029), per side.

    One offset of the whole section fixes both errors a fat line makes: the outside comes
    in and every hole opens up by the same amount — what "horizontal expansion" does in
    desktop slicers, here with the number the user measured rather than a guessed one.
    """
    if not xy_compensation_mm:
        return polygons
    return [
        part
        for polygon in polygons
        for part in _as_polygons(polygon.buffer(-xy_compensation_mm, join_style="mitre"))
        if part.area > 1e-6
    ]


def _placed_on_bed(mesh: trimesh.Trimesh, printer: PrinterProfile) -> tuple[trimesh.Trimesh, bool]:
    """A copy standing on z=0 and centred on the bed: G-code is in the printer's own
    coordinates (a Marlin origin is the bed's front-left corner), not the model's — a part
    modelled around (0, 0) would otherwise send the head to negative X/Y. Turned 90 degrees
    about Z when it only fits that way, the rule the layer preview already applies.

    A measured shrinkage (the coupon's 60 mm edge) is paid for here, by printing the part
    that much larger in X/Y — before the bed check, since that is the size that must fit."""
    placed = mesh.copy()
    if printer.shrinkage_pct:
        grow = 1.0 / (1.0 - printer.shrinkage_pct / 100.0)
        placed.apply_transform(np.diag([grow, grow, 1.0, 1.0]))
    x, y, z = (float(v) for v in placed.extents)
    turned = False
    if not (x <= printer.bed_x_mm and y <= printer.bed_y_mm):
        if not (y <= printer.bed_x_mm and x <= printer.bed_y_mm):
            raise ValueError("model exceeds the printer bed in X/Y; cut it into parts first")
        quarter_turn = np.array(
            [
                [0.0, -1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        placed.apply_transform(quarter_turn)
        turned = True
    if z > printer.bed_z_mm:
        raise ValueError("model exceeds the printer height; cut it into parts first")
    lo, hi = np.asarray(placed.bounds, dtype=float)
    placed.apply_translation(
        (
            printer.bed_x_mm / 2 - (lo[0] + hi[0]) / 2,
            printer.bed_y_mm / 2 - (lo[1] + hi[1]) / 2,
            -lo[2],
        )
    )
    return placed, turned


def _skirt(mesh: trimesh.Trimesh, printer: PrinterProfile, bed_z: float) -> Path2:
    """A priming loop SKIRT_GAP_MM outside the first layer's outline (its convex hull, so
    one loop), left out when it would run off the bed."""
    first = _polygons_at(mesh, bed_z + min(printer.layer_height_mm / 2, mesh.extents[2] / 2))
    if not first:
        return []
    outline = unary_union(first).convex_hull.buffer(SKIRT_GAP_MM)
    minx, miny, maxx, maxy = outline.bounds
    if minx < 0 or miny < 0 or maxx > printer.bed_x_mm or maxy > printer.bed_y_mm:
        return []
    return [(round(x, 3), round(y, 3)) for x, y in outline.exterior.coords]


def _brim(
    first_layer: list[Polygon], printer: PrinterProfile, line_width: float, brim_mm: float
) -> list[Path2]:
    """Loops hugging the first layer's outside, innermost first, none that leave the bed."""
    if not first_layer or brim_mm <= 0:
        return []
    solid = unary_union([Polygon(p.exterior) for p in first_layer])
    loops: list[Path2] = []
    for k in range(max(1, math.ceil(brim_mm / line_width))):
        for part in _as_polygons(solid.buffer(line_width * (k + 0.5), join_style="round")):
            minx, miny, maxx, maxy = part.bounds
            if minx < 0 or miny < 0 or maxx > printer.bed_x_mm or maxy > printer.bed_y_mm:
                return loops  # the rest would run off the bed
            loops.append([(round(x, 3), round(y, 3)) for x, y in part.exterior.coords])
    return loops


def _header(printer: PrinterProfile, settings: SliceSettings, total_layers: int) -> list[str]:
    nozzle_c, bed_c = PRINT_TEMPS_C.get(settings.material_id, PRINT_TEMPS_C["pla"])
    nozzle_c = max(nozzle_c + settings.tuning.nozzle_offset_c, MIN_NOZZLE_C)
    bed_c = max(bed_c + settings.tuning.bed_offset_c, 0.0)
    return [
        f"; generated by Physical AI 3D slicer v1 for {printer.name}",
        f"; material={settings.material_id} layer_height={printer.layer_height_mm:g}mm "
        f"nozzle={printer.nozzle_mm:g}mm infill={settings.infill_density_pct:g}% "
        f"walls={settings.wall_count} supports={settings.supports}",
        f"; layers={total_layers}",
        f"M140 S{bed_c:g}",
        f"M104 S{nozzle_c:g}",
        "G28",
        f"M190 S{bed_c:g}",
        f"M109 S{nozzle_c:g}",
        "G21",
        "G90",
        "M83",
        "G92 E0",
    ]


def _footer() -> list[str]:
    return ["M104 S0", "M140 S0", "G91", "G1 Z5 F600", "G90", "M84"]


def slice_mesh(
    mesh: trimesh.Trimesh, printer: PrinterProfile, settings: SliceSettings
) -> tuple[str, SliceStats]:
    if printer.technology != "fdm":
        raise ValueError("G-code generation currently supports FDM printers only")
    if mesh.is_empty or not mesh.is_watertight:
        raise ValueError("repair the mesh into a closed solid before slicing")
    if printer.layer_height_mm <= 0 or printer.layer_height_mm > printer.nozzle_mm * 0.8:
        raise ValueError("layer height must be at most 80% of the nozzle diameter")
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    if not np.isfinite(bounds).all() or (extents <= 0).any():
        raise ValueError("mesh bounds are invalid")
    mesh, turned = _placed_on_bed(mesh, printer)
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    total_layers = max(1, math.ceil(float(extents[2]) / printer.layer_height_mm))
    if total_layers > MAX_LAYERS:
        raise ValueError("too many layers; use a larger layer height")

    line_width = printer.nozzle_mm
    density = max(settings.infill_density_pct, 0.0)
    spacing = line_width / (density / 100.0) if density > 0 else 0.0
    support_pts = _support_columns(mesh, printer) if settings.supports else Supports([])
    bed_z = float(bounds[0][2])
    # The tiling itself never changes between layers, only what of it survives clipping to
    # that layer's own cross-section — built once here rather than per layer, so a
    # many-layer honeycomb print still fits in the sandbox's wall-clock budget.
    hex_grid = (
        _hex_tiling_grid(
            float(bounds[0][0]),
            float(bounds[0][1]),
            float(bounds[1][0]),
            float(bounds[1][1]),
            spacing,
        )
        if settings.infill_pattern == "honeycomb" and spacing > 0
        else None
    )

    tuning = settings.tuning
    writer = _Writer(
        printer,
        retraction_mm=tuning.retraction_mm,
        retraction_speed_mm_s=35.0,
        # the printer's measured flow (coupon) times what print reports taught this material
        flow=printer.flow_pct / 100.0 * tuning.flow_pct / 100.0,
    )
    writer.lines.extend(_header(printer, settings, total_layers))
    writer.comment(
        f"placed: centred on the {printer.bed_x_mm:g} x {printer.bed_y_mm:g} mm bed"
        + (", turned 90 degrees to fit" if turned else "")
    )
    if printer.xy_compensation_mm or printer.shrinkage_pct or printer.flow_pct != 100.0:
        writer.comment(
            "calibration (measured on this printer's coupon): "
            f"outlines {-printer.xy_compensation_mm:+g} mm per side, "
            f"X/Y scaled for {printer.shrinkage_pct:g}% shrinkage, "
            f"flow {printer.flow_pct:g}%"
        )
    learned = tuning.changes()
    if learned:
        writer.comment(
            "tuning (learned from print reports): "
            + ", ".join(f"{name}={value:g}" for name, value in learned.items())
        )

    if settings.skirt and not tuning.brim_mm:
        skirt = _skirt(mesh, printer, bed_z)
        if skirt:
            writer.set_z(printer.layer_height_mm)
            writer.loop(skirt, line_width)

    # Far behind the part (+Y), centred: the nearest corner of every loop is its rearmost.
    seam_anchor = (
        float(bounds[0][0] + extents[0] / 2),
        float(bounds[1][1] + 10 * max(float(extents[0]), float(extents[1]))),
    )

    def here() -> tuple[float, float]:
        if writer.x is None or writer.y is None:
            return seam_anchor
        return writer.x, writer.y

    base_feed = writer.print_feed
    brim_loops = 0
    for index in range(total_layers):
        section_z = bed_z + min((index + 0.5) * printer.layer_height_mm, float(extents[2]) - 1e-6)
        machine_z = round((index + 1) * printer.layer_height_mm, 3)
        pull_in = printer.xy_compensation_mm + (tuning.elephant_foot_mm if index == 0 else 0.0)
        polygons = _compensated(_polygons_at(mesh, section_z), pull_in)
        writer.comment(f"layer {index + 1}/{total_layers} z={machine_z:g}")
        writer.set_z(machine_z)
        writer.print_feed = base_feed * (tuning.first_layer_speed_pct / 100 if index == 0 else 1)
        if index == 0:
            for loop in _brim(polygons, printer, line_width, tuning.brim_mm):
                writer.loop(loop, line_width)
                brim_loops += 1
        angle = 0.0 if index % 2 == 0 else 90.0
        for polygon in polygons:
            rings, infill_area = _perimeter_rings(polygon, line_width, settings.wall_count)
            for ring in rings:
                writer.loop(_seam_first(ring, seam_anchor), line_width)
            if spacing > 0:
                fill = (
                    _honeycomb_lines(infill_area, spacing, grid=hex_grid)
                    if settings.infill_pattern == "honeycomb"
                    else _infill_lines(infill_area, spacing, angle)
                )
                for line in _nearest_first(fill, here()):
                    writer.loop(line, line_width)
        outlines, roof = _support_paths(
            support_pts, section_z, polygons, printer, line_width, bed_z
        )
        for column in _nearest_first(outlines, here()):
            writer.loop(column, SUPPORT_WIDTH_MM)
        for line in _nearest_first(roof, here()):
            writer.loop(line, line_width)

    writer.lines.extend(_footer())
    gcode_text = "\n".join(writer.lines) + "\n"

    material_g = writer.filament_mm / 1000.0 * math.pi * (FILAMENT_DIAMETER_MM / 2) ** 2 * 1.24
    stats = SliceStats(
        total_layers=total_layers,
        filament_used_mm=round(writer.filament_mm, 1),
        filament_used_g=round(material_g, 2),
        estimated_time_s=round(
            total_layers * printer.layer_height_mm * 8 + writer.filament_mm / 5, 1
        ),
        support_columns=len(support_pts.columns),
        travel_mm=round(writer.travel_mm, 1),
        xy_compensation_mm=printer.xy_compensation_mm,
        shrinkage_pct=printer.shrinkage_pct,
        flow_pct=printer.flow_pct,
        tuning=learned,
        brim_loops=brim_loops,
        gcode_file="print.gcode",
        gcode_sha256="",
        gcode_bytes=len(gcode_text.encode("utf-8")),
    )
    return gcode_text, stats


def slice_to_file(
    mesh: trimesh.Trimesh, printer: PrinterProfile, settings: SliceSettings, out_dir: Path
) -> SliceStats:
    gcode_text, stats = slice_mesh(mesh, printer, settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / stats.gcode_file
    path.write_text(gcode_text, encoding="utf-8", newline="\n")
    stats.gcode_sha256 = hashlib.sha256(gcode_text.encode("utf-8")).hexdigest()
    return stats


def slice_file_in_sandbox(
    mesh_path: Path, printer: PrinterProfile, settings: SliceSettings, out_dir: Path
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = out_dir / "slice_config.json"
    config.write_text(
        json.dumps({"printer": printer.model_dump(), "settings": settings.model_dump()}),
        encoding="utf-8",
    )
    outcome = sandbox.run(
        "worker.gcode_child",
        [str(mesh_path), str(config), str(out_dir)],
        input_path=mesh_path,
        limits=SLICE_LIMITS,
    )
    if not outcome.ok:
        raise ValueError(outcome.message)
    result = outcome.output or {}
    if not result.get("ok"):
        raise ValueError(str(result.get("message", "could not slice the model")))
    return dict(result["stats"])


def load_stl(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, file_type="stl", force="mesh", process=False)
    mesh = as_single_mesh(loaded)
    if mesh is None:
        raise ValueError("no mesh geometry")
    mesh.merge_vertices()
    return mesh
