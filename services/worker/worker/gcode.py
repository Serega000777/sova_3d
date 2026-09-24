"""Real slicing (F-054, second stage): perimeters, infill and machine G-code.

`slicing.py` only samples cross-section contours for a viewer. This module walks every
layer of a watertight mesh, offsets each layer's polygons (trimesh + shapely handle the
holes) into `wall_count` perimeter loops, fills what is left with rectilinear infill at
the requested density, and writes the whole toolpath as G-code a Marlin-family firmware
can run: absolute XY, relative extrusion (M83), one retract per travel move.

Supports are straight columns under faces steeper than the printer's overhang limit —
one column per grid cell of the bed, from the plate up to the lowest point that needs
holding up. Not tree supports; a single thin perimeter loop per layer, weak enough to
snap off by hand, the way a beginner-friendly default should be.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

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

SUPPORT_GRID_MM = 4.0
SUPPORT_WIDTH_MM = 1.6
CONTACT_EPS_MM = 0.05


class SliceSettings(BaseModel):
    material_id: str = "pla"
    infill_density_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    wall_count: int = Field(default=2, ge=1, le=6)
    supports: bool = False
    skirt: bool = True


class SliceStats(BaseModel):
    total_layers: int
    filament_used_mm: float
    filament_used_g: float
    estimated_time_s: float
    support_columns: int
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
    planar, _ = section.to_2D()
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


def _support_columns(
    mesh: trimesh.Trimesh, printer: PrinterProfile, spacing_mm: float = SUPPORT_GRID_MM
) -> list[tuple[float, float, float]]:
    """(x, y, top_z) in the mesh's own frame — one straight column per grid cell."""
    normals = np.asarray(mesh.face_normals)
    areas = np.asarray(mesh.area_faces)
    centroids = np.asarray(mesh.triangles_center)
    bed_z = float(mesh.bounds[0][2])
    down = -normals[:, 2]
    threshold = math.cos(math.radians(printer.max_overhang_deg))
    on_bed = centroids[:, 2] - bed_z <= CONTACT_EPS_MM
    unsupported = (down > threshold) & ~on_bed & (areas > 1e-6)
    if not unsupported.any():
        return []
    cells: dict[tuple[int, int], float] = {}
    for x, y, z in centroids[unsupported]:
        key = (round(float(x) / spacing_mm), round(float(y) / spacing_mm))
        if key not in cells or z < cells[key]:
            cells[key] = float(z)
    return [
        (key[0] * spacing_mm, key[1] * spacing_mm, top)
        for key, top in cells.items()
        if top - bed_z > printer.layer_height_mm
    ]


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

    def __init__(self, printer: PrinterProfile, retraction_mm: float, retraction_speed_mm_s: float):
        self.lines: list[str] = []
        self.printer = printer
        self.retraction_mm = retraction_mm
        self.retract_feed = retraction_speed_mm_s * 60
        self.travel_feed = printer.print_speed_mm_s * 60 * 2
        self.print_feed = printer.print_speed_mm_s * 60
        self.filament_mm = 0.0
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
        self.lines.append(f"G1 X{x:.3f} Y{y:.3f} F{self.travel_feed:.0f}")

    def loop(self, points: list[tuple[float, float]], line_width_mm: float) -> None:
        if len(points) < 2:
            return
        self._travel_to(*points[0])
        self.x, self.y = points[0]
        for x, y in points[1:]:
            length = math.hypot(x - (self.x or x), y - (self.y or y))
            if length <= 1e-6:
                continue
            if not self.extruding:
                self.lines.append(f"G1 E{self.retraction_mm:.4f} F{self.retract_feed:.0f}")
                self.extruding = True
            e = _extrusion_mm(length, self.printer, line_width_mm)
            self.filament_mm += e
            self.lines.append(f"G1 X{x:.3f} Y{y:.3f} E{e:.5f} F{self.print_feed:.0f}")
            self.x, self.y = x, y


def _header(printer: PrinterProfile, settings: SliceSettings, total_layers: int) -> list[str]:
    nozzle_c, bed_c = PRINT_TEMPS_C.get(settings.material_id, PRINT_TEMPS_C["pla"])
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
    total_layers = max(1, math.ceil(float(extents[2]) / printer.layer_height_mm))
    if total_layers > MAX_LAYERS:
        raise ValueError("too many layers; use a larger layer height")

    line_width = printer.nozzle_mm
    density = max(settings.infill_density_pct, 0.0)
    spacing = line_width / (density / 100.0) if density > 0 else 0.0
    support_pts = _support_columns(mesh, printer) if settings.supports else []
    bed_z = float(bounds[0][2])

    writer = _Writer(printer, retraction_mm=1.2, retraction_speed_mm_s=35.0)
    writer.lines.extend(_header(printer, settings, total_layers))

    if settings.skirt:
        cx, cy = float(bounds[0][0] + extents[0] / 2), float(bounds[0][1] + extents[1] / 2)
        radius = max(float(extents[0]), float(extents[1])) / 2 + 5
        skirt = [
            (
                cx + radius * math.cos(a),
                cy + radius * math.sin(a),
            )
            for a in np.linspace(0, 2 * math.pi, 33)
        ]
        writer.set_z(printer.layer_height_mm)
        writer.loop(skirt, line_width)

    for index in range(total_layers):
        section_z = bed_z + min((index + 0.5) * printer.layer_height_mm, float(extents[2]) - 1e-6)
        machine_z = round((index + 1) * printer.layer_height_mm, 3)
        polygons = _polygons_at(mesh, section_z)
        writer.comment(f"layer {index + 1}/{total_layers} z={machine_z:g}")
        writer.set_z(machine_z)
        angle = 0.0 if index % 2 == 0 else 90.0
        for polygon in polygons:
            rings, infill_area = _perimeter_rings(polygon, line_width, settings.wall_count)
            for ring in rings:
                writer.loop(ring, line_width)
            if spacing > 0:
                for line in _infill_lines(infill_area, spacing, angle):
                    writer.loop(line, line_width)
        for x, y, top in support_pts:
            if top >= section_z:
                writer.loop(_square(x, y, SUPPORT_WIDTH_MM), SUPPORT_WIDTH_MM)

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
        support_columns=len(support_pts),
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
