"""Real slicing (F-054, second stage): perimeters, infill and machine G-code.

`slicing.py` only samples cross-section contours for a viewer. This module walks every
layer of a watertight mesh, offsets each layer's polygons (trimesh + shapely handle the
holes) into `wall_count` perimeter loops, fills what is left at the requested density —
either straight lines (alternating 0/90 degrees per layer) or a real hexagonal tiling
(`infill_pattern="honeycomb"`; a true honeycomb, not three crossed line families, which
tile triangles instead) — and writes the whole toolpath as G-code a Marlin-family
firmware can run: absolute XY, relative extrusion (M83), one retract per travel move.
Every loop starts at its rearmost corner so the seams stack into one line at the back,
and infill/support paths are printed nearest-first, then improved with bounded 2-opt,
to cut travel without slowing dense layers excessively.

Supports can be the original straight grid columns or lightweight trees. A tree keeps
the same sampled contact points under steep faces, steers them down at no more than 50°
from vertical, and merges nearby branches into a shared trunk. Contact tips have a small
two-layer interface instead of the grid's full cells, reducing material and scars.
Validated model-space paint strokes can block automatic contacts or enforce contacts on a
gentler downward face; they are evaluated before bed placement and then carried with the
same face indices into either support planner.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import shapely
import trimesh
from pydantic import BaseModel, Field, model_validator
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from worker import paint, sandbox
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
MAX_TWO_OPT_PATHS = 300
MAX_TWO_OPT_PASSES = 4
SKIRT_GAP_MM = 5.0
SUPPORT_GRID_MM = 4.0
SUPPORT_WIDTH_MM = 1.6
# One empty layer between support and part, so the support snaps off instead of fusing on,
# and two dense layers right under the overhang so its underside prints on a floor.
SUPPORT_Z_GAP_LAYERS = 1
SUPPORT_INTERFACE_LAYERS = 2
CONTACT_EPS_MM = 0.05
TREE_BRANCH_ANGLE_DEG = 50.0
TREE_MERGE_RADIUS_MM = 12.0
TREE_TIP_WIDTH_MM = SUPPORT_WIDTH_MM
MAX_MOUSE_EARS = 8
MOUSE_EAR_MAX_CORNER_ANGLE_DEG = 135.0
PURGE_TOWER_EDGE_MARGIN_MM = 2.0
PURGE_TOWER_CLEARANCE_MM = 3.0


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


class SupportModifier(BaseModel):
    """A model-space area painted to remove or require support contacts.

    Regions deliberately reuse the validated paint/outline geometry. They are evaluated
    against the original mesh before printer placement, so a centred/rotated toolpath does
    not move the user's stroke away from the face it targeted.
    """

    mode: Literal["block", "enforce"]
    region: paint.Region


class ProcessModifier(BaseModel):
    """A bounded local slicing override painted in model-space millimetres.

    The first increment changes sparse infill only. Freehand regions must be painted on a
    horizontal face so their XY footprint remains exact through the slicer's bed placement.
    """

    infill_density_pct: float = Field(ge=0.0, le=100.0)
    print_speed_pct: float = Field(default=100.0, ge=20.0, le=200.0)
    nozzle_temperature_offset_c: float = Field(default=0.0, ge=-20.0, le=20.0)
    infill_pattern: Literal["lines", "honeycomb"] | None = None
    wall_count: int | None = Field(default=None, ge=1, le=6)
    material_slot: int | None = Field(default=None, ge=0, le=15)
    material_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    region: paint.Region

    @model_validator(mode="after")
    def horizontal_lasso_only(self) -> ProcessModifier:
        if isinstance(self.region, paint.LassoRegion) and self.region.axis != "z":
            raise ValueError("local infill must be painted on a horizontal face")
        if (self.material_slot is None) != (self.material_id is None):
            raise ValueError("material slot and resolved material id must be provided together")
        return self


class SliceSettings(BaseModel):
    material_id: str = "pla"
    infill_density_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    infill_pattern: Literal["lines", "honeycomb"] = "lines"
    wall_count: int = Field(default=2, ge=1, le=6)
    top_solid_layers: int = Field(default=4, ge=0, le=20)
    bottom_solid_layers: int = Field(default=4, ge=0, le=20)
    adaptive_layer_height: bool = False
    min_layer_height_mm: float | None = Field(default=None, ge=0.04, le=1.0)
    max_layer_height_mm: float | None = Field(default=None, ge=0.04, le=1.0)
    supports: bool = False
    support_type: Literal["grid", "tree"] = "grid"
    support_generation_mode: Literal["auto", "painted_only"] = "auto"
    support_modifiers: list[SupportModifier] = Field(default_factory=list, max_length=256)
    process_modifiers: list[ProcessModifier] = Field(default_factory=list, max_length=64)
    tool_change_mode: Literal["disabled", "marlin_tn"] = "disabled"
    tool_count: int = Field(default=1, ge=1, le=16)
    base_tool: int = Field(default=0, ge=0, le=15)
    purge_tower_enabled: bool = False
    purge_tower_width_mm: float = Field(default=20.0, ge=10.0, le=40.0)
    purge_volume_mm3: float = Field(default=60.0, ge=10.0, le=500.0)
    adhesion_mode: Literal["auto", "skirt", "brim", "mouse_ears", "raft", "none"] = "auto"
    brim_width_mm: float = Field(default=5.0, ge=1.0, le=15.0)
    mouse_ear_diameter_mm: float = Field(default=10.0, ge=5.0, le=30.0)
    mouse_ear_points_mm: list[tuple[float, float, float]] = Field(
        default_factory=list, max_length=32
    )
    adhesion_speed_pct: float = Field(default=100.0, ge=20.0, le=100.0)
    raft_margin_mm: float = Field(default=5.0, ge=3.0, le=15.0)
    raft_base_layers: int = Field(default=1, ge=1, le=3)
    raft_interface_layers: int = Field(default=1, ge=1, le=3)
    raft_base_layer_height_mm: float | None = Field(default=None, ge=0.04, le=1.0)
    raft_interface_layer_height_mm: float | None = Field(default=None, ge=0.04, le=1.0)
    raft_base_speed_pct: float = Field(default=100.0, ge=20.0, le=100.0)
    raft_interface_speed_pct: float = Field(default=100.0, ge=20.0, le=100.0)
    raft_air_gap_mm: float = Field(default=0.15, ge=0.05, le=0.5)
    raft_base_density_pct: float = Field(default=40.0, ge=10.0, le=70.0)
    raft_interface_density_pct: float = Field(default=100.0, ge=50.0, le=100.0)
    raft_density_profiled: bool = False
    skirt: bool = True
    tuning: PrintTuning = Field(default_factory=PrintTuning)

    @model_validator(mode="after")
    def tool_change_capability_is_coherent(self) -> SliceSettings:
        if self.tool_change_mode == "marlin_tn" and self.tool_count < 2:
            raise ValueError("Marlin Tn mode requires at least two tools")
        if self.tool_change_mode == "marlin_tn" and self.base_tool >= self.tool_count:
            raise ValueError("base tool exceeds the configured tool count")
        if self.tool_change_mode == "marlin_tn" and any(
            modifier.material_slot is not None and modifier.material_slot >= self.tool_count
            for modifier in self.process_modifiers
        ):
            raise ValueError("assigned material slot exceeds the configured tool count")
        if self.tool_change_mode == "disabled" and self.purge_tower_enabled:
            raise ValueError("purge tower requires Marlin Tn mode")
        return self

    @model_validator(mode="after")
    def layer_height_range_is_ordered(self) -> SliceSettings:
        if (
            self.min_layer_height_mm is not None
            and self.max_layer_height_mm is not None
            and self.min_layer_height_mm > self.max_layer_height_mm
        ):
            raise ValueError("minimum layer height must not exceed maximum layer height")
        if self.mouse_ear_points_mm and self.adhesion_mode != "mouse_ears":
            raise ValueError("mouse-ear points require mouse-ear adhesion")
        if self.mouse_ear_points_mm and not np.isfinite(self.mouse_ear_points_mm).all():
            raise ValueError("mouse-ear points must be finite model-space coordinates")
        if self.support_generation_mode == "painted_only" and not self.supports:
            raise ValueError("painted-only support generation requires supports to be enabled")
        return self


class SliceStats(BaseModel):
    total_layers: int
    layer_height_mode: Literal["fixed", "adaptive"] = "fixed"
    min_layer_height_mm: float
    max_layer_height_mm: float
    filament_used_mm: float
    filament_used_by_tool_mm: dict[str, float] = Field(default_factory=dict)
    filament_used_g: float
    estimated_time_s: float
    support_columns: int
    support_type: Literal["grid", "tree"] = "grid"
    support_generation_mode: Literal["auto", "painted_only"] = "auto"
    support_branches: int = 0
    support_trunks: int = 0
    support_modifiers: int = 0
    support_blocked_faces: int = 0
    support_enforced_faces: int = 0
    process_modifiers: int = 0
    process_modified_layers: int = 0
    material_assigned_regions: int = 0
    planned_tool_change_layers: int = 0
    planned_tool_changes: int = 0
    planned_purge_volume_mm3: float = 0.0
    purge_tower_reserved: bool = False
    purge_tower_x_mm: float = 0.0
    purge_tower_y_mm: float = 0.0
    purge_tower_width_mm: float = 0.0
    # Non-printing head moves: what path ordering (_nearest_first) exists to cut.
    travel_mm: float = 0.0
    # The printer's measured calibration as applied to this toolpath (0 = none on file).
    xy_compensation_mm: float = 0.0
    shrinkage_pct: float = 0.0
    flow_pct: float = 100.0
    # F-056: the learned corrections this G-code carries (empty = none)
    tuning: dict[str, float] = Field(default_factory=dict)
    adhesion_mode: Literal["skirt", "brim", "mouse_ears", "raft", "none"] = "none"
    brim_width_mm: float = 0.0
    brim_loops: int = 0
    mouse_ear_diameter_mm: float = 0.0
    mouse_ear_count: int = 0
    mouse_ear_requested_count: int = 0
    mouse_ear_rejected_count: int = 0
    adhesion_speed_pct: float = 100.0
    raft_layers: int = 0
    raft_base_layers: int = 0
    raft_interface_layers: int = 0
    raft_base_layer_height_mm: float = 0.0
    raft_interface_layer_height_mm: float = 0.0
    raft_base_speed_pct: float = 0.0
    raft_interface_speed_pct: float = 0.0
    raft_margin_mm: float = 0.0
    raft_air_gap_mm: float = 0.0
    raft_base_density_pct: float = 0.0
    raft_interface_density_pct: float = 0.0
    raft_density_profiled: bool = False
    solid_skin_paths: int = 0
    gcode_file: str
    gcode_sha256: str
    gcode_bytes: int


@dataclass(frozen=True, slots=True)
class LayerPlan:
    """One deposited layer in printer coordinates."""

    sample_z: float
    machine_z: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class PurgePlan:
    """Validated future transition order and its reserved, non-printing tower footprint."""

    layer_tools: tuple[tuple[int, ...], ...]
    tower: Polygon | None

    @property
    def change_count(self) -> int:
        return sum(max(0, len(tools) - 1) for tools in self.layer_tools)

    @property
    def changed_layer_count(self) -> int:
        return sum(len(tools) > 1 for tools in self.layer_tools)


@dataclass(frozen=True, slots=True)
class ToolThermalTarget:
    """One exact, validated material temperature target for a future active tool."""

    tool: int
    material_id: str
    nozzle_c: float


@dataclass(frozen=True, slots=True)
class ThermalPlan:
    """Dormant per-tool thermal prerequisites without activating tool or heater changes."""

    base_tool: int
    bed_c: float
    targets: tuple[ToolThermalTarget, ...]

    @property
    def used_tools(self) -> tuple[int, ...]:
        return tuple(target.tool for target in self.targets)

    def nozzle_c_for(self, tool: int) -> float:
        for target in self.targets:
            if target.tool == tool:
                return target.nozzle_c
        raise ValueError(f"tool T{tool} is not present in the thermal plan")

    def local_nozzle_c_for(self, tool: int, offset_c: float) -> float:
        return max(self.nozzle_c_for(tool) + offset_c, MIN_NOZZLE_C)


@dataclass(frozen=True, slots=True)
class PurgeTowerLayerSegments:
    """Dormant purge geometry partitioned for a future tool-change emitter."""

    centerline: LineString
    structural: LineString
    purge: tuple[LineString, ...]


MaterialPathCounts = dict[int, dict[str, int]]
MaterialToolAreas = tuple[tuple[int, BaseGeometry], ...]


@dataclass(frozen=True, slots=True)
class MaterialPathBatch:
    """One process-compatible group of real paths assigned to one material tool."""

    tool: int
    kind: str
    comment: str
    paths: tuple[Path2, ...]
    line_width_mm: float
    nearest_first: bool
    modifier: ProcessModifier | None = None


@dataclass(frozen=True, slots=True)
class LayerMaterialPlan:
    """Memory-bounded exact material summary retained between preflight and emission."""

    counts: MaterialPathCounts
    tool_order: tuple[int, ...]
    blocked_candidate_mask: int = 0


ImmutablePath2 = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class AdhesionPathPlan:
    """Exact first-layer paths shared by purge reservation and G-code emission."""

    skirt: ImmutablePath2 = ()
    brim: tuple[ImmutablePath2, ...] = ()
    mouse_ears: tuple[ImmutablePath2, ...] = ()
    mouse_ear_count: int = 0


def _resolved_adaptive_range(
    printer: PrinterProfile, settings: SliceSettings
) -> tuple[float, float]:
    nozzle_limit = printer.nozzle_mm * 0.8
    minimum = settings.min_layer_height_mm or max(0.04, printer.layer_height_mm * 0.5)
    maximum = settings.max_layer_height_mm or min(nozzle_limit, printer.layer_height_mm * 1.5)
    if minimum > maximum:
        raise ValueError("minimum layer height must not exceed maximum layer height")
    if maximum > nozzle_limit + 1e-9:
        raise ValueError("maximum layer height must be at most 80% of the nozzle diameter")
    return minimum, maximum


def _bounded_sum(desired: list[float], total: float, minimum: float, maximum: float) -> list[float]:
    """Keep geometric preferences while making bounded layer heights sum to the model."""
    values = [min(max(value, minimum), maximum) for value in desired]
    for _ in range(len(values) + 2):
        delta = total - sum(values)
        if abs(delta) <= 1e-9:
            break
        if delta > 0:
            active = [index for index, value in enumerate(values) if value < maximum - 1e-9]
            if not active:
                break
            share = delta / len(active)
            for index in active:
                values[index] += min(share, maximum - values[index])
        else:
            active = [index for index, value in enumerate(values) if value > minimum + 1e-9]
            if not active:
                break
            share = -delta / len(active)
            for index in active:
                values[index] -= min(share, values[index] - minimum)
    return values


def _layer_plan(
    mesh: trimesh.Trimesh, printer: PrinterProfile, settings: SliceSettings
) -> list[LayerPlan]:
    """Create fixed layers or geometry-driven adaptive layers.

    Adaptive layers get thinner where upcoming faces point upwards/downwards (where a
    coarse Z step creates visible stair-stepping) and thicker on nearly vertical walls.
    The bounded-sum pass preserves the requested range while landing exactly on the top
    of the model instead of leaving a dangerously thin remainder layer.
    """
    bed_z = float(mesh.bounds[0][2])
    height = float(mesh.extents[2])
    if not settings.adaptive_layer_height:
        total = max(1, math.ceil(height / printer.layer_height_mm))
        return [
            LayerPlan(
                sample_z=bed_z + min((index + 0.5) * printer.layer_height_mm, height - 1e-6),
                machine_z=bed_z + (index + 1) * printer.layer_height_mm,
                height_mm=printer.layer_height_mm,
            )
            for index in range(total)
        ]

    minimum, maximum = _resolved_adaptive_range(printer, settings)
    if height <= minimum:
        return [
            LayerPlan(
                sample_z=bed_z + height / 2,
                machine_z=bed_z + height,
                height_mm=height,
            )
        ]

    triangles = np.asarray(mesh.triangles, dtype=float)
    triangle_low = triangles[:, :, 2].min(axis=1)
    triangle_high = triangles[:, :, 2].max(axis=1)
    upward = np.abs(np.asarray(mesh.face_normals, dtype=float)[:, 2])

    def desired_at(relative_z: float) -> float:
        absolute_z = bed_z + relative_z
        active = (triangle_high >= absolute_z - 1e-6) & (
            triangle_low <= absolute_z + maximum + 1e-6
        )
        detail = float(upward[active].max()) if active.any() else 0.0
        return maximum - (maximum - minimum) * detail**2

    rough: list[float] = []
    cursor = 0.0
    while cursor < height - 1e-9:
        target = (
            min(max(printer.layer_height_mm, minimum), maximum) if not rough else desired_at(cursor)
        )
        rough.append(target)
        cursor += target

    smallest_count = max(1, math.ceil(height / maximum - 1e-9))
    largest_count = max(1, math.floor(height / minimum + 1e-9))
    # Some short heights cannot be divided into any integer number of layers inside a
    # narrow requested band (for example 0.31 mm with a 0.20–0.30 mm range). Never exceed
    # the maximum/nozzle limit: spread the correction over the minimum required count.
    effective_minimum = minimum
    if smallest_count > largest_count:
        count = smallest_count
        effective_minimum = min(minimum, height / count)
    else:
        count = min(max(len(rough), smallest_count), largest_count)
    desired = [
        (
            min(max(printer.layer_height_mm, minimum), maximum)
            if index == 0
            else desired_at(height * index / count)
        )
        for index in range(count)
    ]
    heights = _bounded_sum(desired, height, effective_minimum, maximum)

    plans: list[LayerPlan] = []
    bottom = bed_z
    for height_mm in heights:
        top = bottom + height_mm
        plans.append(
            LayerPlan(
                sample_z=(bottom + top) / 2,
                machine_z=top,
                height_mm=height_mm,
            )
        )
        bottom = top
    return plans


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


def _solid_skin_areas(
    infill_area: list[Polygon],
    layer_footprints: Sequence[BaseGeometry],
    layer_index: int,
    top_layers: int,
    bottom_layers: int,
) -> tuple[list[Polygon], list[Polygon]]:
    """Split a layer's inner area into dense exposed skins and ordinary sparse infill.

    A region is top skin when it will become exposed within ``top_layers`` layers, and
    bottom skin when it appeared within ``bottom_layers`` layers. Comparing several
    neighbouring footprints, rather than only the first/last layer of the whole model,
    also closes intermediate ledges and the undersides of overhangs.
    """
    current: BaseGeometry = unary_union(infill_area)
    if current.is_empty or (top_layers <= 0 and bottom_layers <= 0):
        return [], infill_area

    dense: BaseGeometry | None = None

    def covered_by(indices: range) -> BaseGeometry:
        coverage: BaseGeometry | None = None
        for index in indices:
            if index < 0 or index >= len(layer_footprints):
                return Polygon()
            footprint = layer_footprints[index]
            coverage = footprint if coverage is None else coverage.intersection(footprint)
            if coverage.is_empty:
                break
        return coverage if coverage is not None else current

    if top_layers > 0:
        top_cover = covered_by(range(layer_index + 1, layer_index + top_layers + 1))
        dense = current.difference(top_cover)
    if bottom_layers > 0:
        bottom_cover = covered_by(range(layer_index - 1, layer_index - bottom_layers - 1, -1))
        bottom_skin = current.difference(bottom_cover)
        dense = bottom_skin if dense is None else dense.union(bottom_skin)

    dense = dense.intersection(current) if dense is not None else Polygon()
    sparse = current.difference(dense)
    return _as_polygons(dense), _as_polygons(sparse)


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
    crossing the part between neighbouring segments. A bounded 2-opt pass then removes
    local detours left by the greedy choices. Past MAX_ORDERED_PATHS the O(n^2) search
    would cost more than it saves, so the generation order (already a sweep) stands.
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
    return _two_opt_route(ordered, start)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _travel_length(paths: list[Path2], start: tuple[float, float]) -> float:
    here = start
    total = 0.0
    for path in paths:
        total += _distance(here, path[0])
        here = path[-1]
    return total


def _two_opt_route(paths: list[Path2], start: tuple[float, float]) -> list[Path2]:
    """Remove local detours from an open route without changing extrusion geometry.

    Reversing a consecutive block and every path in it preserves the block's internal
    travel distances; only its two boundary jumps change. Each accepted move therefore
    has a measured benefit. The pass is bounded so dense layers keep slicing promptly.
    """
    if len(paths) < 2 or len(paths) > MAX_TWO_OPT_PATHS:
        return paths
    route = list(paths)
    for _ in range(MAX_TWO_OPT_PASSES):
        improved = False
        for left in range(len(route)):
            before = start if left == 0 else route[left - 1][-1]
            for right in range(left, len(route)):
                after = route[right + 1][0] if right + 1 < len(route) else None
                old = _distance(before, route[left][0])
                new = _distance(before, route[right][-1])
                if after is not None:
                    old += _distance(route[right][-1], after)
                    new += _distance(route[left][0], after)
                if new + 1e-9 < old:
                    route[left : right + 1] = [
                        path[::-1] for path in reversed(route[left : right + 1])
                    ]
                    improved = True
        if not improved:
            break
    return route


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


@dataclass(frozen=True, slots=True)
class SupportBranch:
    """One printable centreline segment, ordered from its lower to upper endpoint."""

    lower_x: float
    lower_y: float
    lower_z: float
    upper_x: float
    upper_y: float
    upper_z: float


@dataclass(frozen=True, slots=True)
class TreeSupports:
    contacts: list[SupportColumn]
    branches: list[SupportBranch]
    trunks: int
    footprint: BaseGeometry | None = None


def _support_face_selection(
    mesh: trimesh.Trimesh,
    printer: PrinterProfile,
    modifiers: list[SupportModifier],
    generation_mode: Literal["auto", "painted_only"] = "auto",
) -> tuple[np.ndarray, int, int]:
    """Return the final face mask plus the paint-on delta from automatic supports.

    Modifiers are replayed in drawing order, so painting an enforcer over a blocker (or
    vice versa) has the same predictable last-stroke-wins behaviour as colour painting.
    Enforcers can relax the configured overhang threshold, but only for downward-facing
    faces above the bed; they never build support through an upward floor or the build plate.
    """
    normals = np.asarray(mesh.face_normals)
    areas = np.asarray(mesh.area_faces)
    centres = np.asarray(mesh.triangles_center)
    bed_z = float(mesh.bounds[0][2])
    down = -normals[:, 2]
    on_bed = centres[:, 2] - bed_z <= CONTACT_EPS_MM
    printable_downward = (down > 1e-6) & ~on_bed & (areas > 1e-6)
    threshold = math.cos(math.radians(printer.max_overhang_deg))
    automatic = printable_downward & (down > threshold)
    baseline = automatic if generation_mode == "auto" else np.zeros_like(automatic)
    selected = baseline.copy()
    for modifier in modifiers:
        covered = paint.inside_region(centres, modifier.region)
        if modifier.mode == "enforce":
            selected |= covered & printable_downward
        else:
            selected &= ~covered
    return (
        selected,
        int(np.count_nonzero(baseline & ~selected)),
        int(np.count_nonzero(selected & ~baseline)),
    )


def _support_columns(
    mesh: trimesh.Trimesh,
    printer: PrinterProfile,
    spacing_mm: float = SUPPORT_GRID_MM,
    unsupported_faces: np.ndarray | None = None,
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
    automatic = (down > threshold) & ~on_bed & (areas > 1e-6)
    unsupported = automatic if unsupported_faces is None else unsupported_faces
    if len(unsupported) != len(mesh.faces):
        raise ValueError("support modifier face mask does not match the mesh")
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


def _segment_clear(
    mesh: trimesh.Trimesh,
    lower: tuple[float, float, float],
    upper: tuple[float, float, float],
) -> bool:
    """Whether a branch reaches its endpoint without crossing the model.

    Touching the supporting surface and the overhang at the two endpoints is expected;
    only intersections in the open segment are collisions.
    """
    vector = np.asarray(upper, dtype=float) - np.asarray(lower, dtype=float)
    length = float(np.linalg.norm(vector))
    if length <= CONTACT_EPS_MM:
        return True
    direction = vector / length
    hits, _, _ = mesh.ray.intersects_location(
        np.asarray([lower], dtype=float), np.asarray([direction], dtype=float), multiple_hits=True
    )
    for hit in hits:
        distance = float(np.dot(np.asarray(hit, dtype=float) - lower, direction))
        if CONTACT_EPS_MM < distance < length - CONTACT_EPS_MM:
            return False
    return True


def _tree_supports(
    mesh: trimesh.Trimesh,
    printer: PrinterProfile,
    spacing_mm: float = SUPPORT_GRID_MM,
    unsupported_faces: np.ndarray | None = None,
) -> TreeSupports:
    """Merge nearby overhang contacts into sloped branches and shared vertical trunks.

    Contacts are inherited from the proven grid detector, including its nearest-surface
    floors. Contacts with similar floors are grouped into bounded XY cells. The contact
    nearest each cell's centroid becomes a trunk; every other contact slopes toward it at
    at most ``TREE_BRANCH_ANGLE_DEG`` from vertical. If there is not enough height to make
    that angle, or either the branch or extended trunk would cross the model, that contact
    remains an independent short trunk. This conservative fallback preserves support for
    low overhangs and complicated cavities.
    """
    grid = _support_columns(mesh, printer, spacing_mm, unsupported_faces)
    if not grid.columns:
        return TreeSupports([], [], 0, grid.footprint)
    bed_z = float(mesh.bounds[0][2])
    gap = printer.layer_height_mm * SUPPORT_Z_GAP_LAYERS
    tangent = math.tan(math.radians(TREE_BRANCH_ANGLE_DEG))
    grouped: dict[tuple[int, int, int], list[SupportColumn]] = {}
    for contact in grid.columns:
        key = (
            round(contact.bottom / printer.layer_height_mm),
            math.floor(contact.x / TREE_MERGE_RADIUS_MM),
            math.floor(contact.y / TREE_MERGE_RADIUS_MM),
        )
        grouped.setdefault(key, []).append(contact)

    branches: list[SupportBranch] = []
    trunk_count = 0
    for contacts in grouped.values():
        centre_x = sum(contact.x for contact in contacts) / len(contacts)
        centre_y = sum(contact.y for contact in contacts) / len(contacts)
        trunk = min(
            contacts,
            key=lambda contact: (
                math.hypot(contact.x - centre_x, contact.y - centre_y),
                contact.x,
                contact.y,
            ),
        )
        trunk_lower = trunk.bottom + (gap if trunk.bottom > bed_z + CONTACT_EPS_MM else 0.0)
        trunk_upper = trunk_lower
        independent: list[SupportBranch] = []
        diagonals: list[SupportBranch] = []
        for contact in contacts:
            lower = contact.bottom + (gap if contact.bottom > bed_z + CONTACT_EPS_MM else 0.0)
            upper = contact.top - gap
            if upper <= lower + CONTACT_EPS_MM:
                continue
            distance = math.hypot(contact.x - trunk.x, contact.y - trunk.y)
            merge_z = upper - distance / tangent
            diagonal_lower = (trunk.x, trunk.y, merge_z)
            diagonal_upper = (contact.x, contact.y, upper)
            proposed_trunk_upper = max(trunk_upper, merge_z)
            trunk_clear = _segment_clear(
                mesh,
                (trunk.x, trunk.y, trunk_lower),
                (trunk.x, trunk.y, proposed_trunk_upper),
            )
            if (
                merge_z >= trunk_lower - CONTACT_EPS_MM
                and trunk_clear
                and _segment_clear(mesh, diagonal_lower, diagonal_upper)
            ):
                trunk_upper = proposed_trunk_upper
                if distance > CONTACT_EPS_MM:
                    diagonals.append(SupportBranch(*diagonal_lower, *diagonal_upper))
                else:
                    trunk_upper = max(trunk_upper, upper)
            else:
                independent.append(
                    SupportBranch(contact.x, contact.y, lower, contact.x, contact.y, upper)
                )

        if trunk_upper > trunk_lower + CONTACT_EPS_MM:
            branches.append(
                SupportBranch(
                    trunk.x,
                    trunk.y,
                    trunk_lower,
                    trunk.x,
                    trunk.y,
                    trunk_upper,
                )
            )
            trunk_count += 1
        branches.extend(diagonals)
        branches.extend(independent)
        trunk_count += len(independent)
    return TreeSupports(grid.columns, branches, trunk_count, grid.footprint)


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


def _tree_support_paths(
    supports: TreeSupports,
    section_z: float,
    part: list[Polygon],
    printer: PrinterProfile,
    line_width: float,
) -> tuple[list[Path2], list[Path2]]:
    """Branch loops and small dense contact tips for one sliced layer."""
    keep_out = unary_union(part).buffer(line_width) if part else None
    branch_cells: list[Polygon] = []
    for branch in supports.branches:
        if not branch.lower_z <= section_z <= branch.upper_z:
            continue
        height = branch.upper_z - branch.lower_z
        ratio = 0.0 if height <= 1e-9 else (section_z - branch.lower_z) / height
        x = branch.lower_x + ratio * (branch.upper_x - branch.lower_x)
        y = branch.lower_y + ratio * (branch.upper_y - branch.lower_y)
        branch_cells.append(Polygon(_square(x, y, SUPPORT_WIDTH_MM)))

    branch_area: BaseGeometry = unary_union(branch_cells) if branch_cells else Polygon()
    if keep_out is not None and not branch_area.is_empty:
        branch_area = branch_area.difference(keep_out)
    outlines: list[Path2] = []
    for area in _as_polygons(branch_area):
        outlines.append([(round(x, 3), round(y, 3)) for x, y in area.exterior.coords])
        outlines.extend(
            [(round(x, 3), round(y, 3)) for x, y in ring.coords] for ring in area.interiors
        )

    gap = printer.layer_height_mm * SUPPORT_Z_GAP_LAYERS
    interface_from = printer.layer_height_mm * (SUPPORT_Z_GAP_LAYERS + SUPPORT_INTERFACE_LAYERS)
    tips: list[Polygon] = []
    for contact in supports.contacts:
        if not contact.top - interface_from <= section_z <= contact.top - gap:
            continue
        tip: BaseGeometry = Polygon(_square(contact.x, contact.y, TREE_TIP_WIDTH_MM))
        if supports.footprint is not None:
            tip = tip.intersection(supports.footprint)
        if keep_out is not None:
            tip = tip.difference(keep_out)
        tips.extend(area for area in _as_polygons(tip) if area.area > line_width**2)
    return outlines, _infill_lines(tips, line_width, 0.0)


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


def _extrusion_mm(length_mm: float, layer_height_mm: float, line_width_mm: float) -> float:
    bead_area = layer_height_mm * line_width_mm
    return (length_mm * bead_area) / _filament_area_mm2()


def _validated_tool_index(tool: object) -> int:
    if isinstance(tool, bool) or not isinstance(tool, int):
        raise TypeError("tool index must be an integer")
    if not 0 <= tool <= 15:
        raise ValueError("tool index must be between 0 and 15")
    return tool


class _Writer:
    """Assembles G-code lines and keeps a running filament/travel tally."""

    def __init__(
        self,
        printer: PrinterProfile,
        retraction_mm: float,
        retraction_speed_mm_s: float,
        active_tool: int,
        flow: float = 1.0,
    ):
        active_tool = _validated_tool_index(active_tool)
        self.lines: list[str] = []
        self.printer = printer
        self.flow = flow
        self.retraction_mm = retraction_mm
        self.retract_feed = retraction_speed_mm_s * 60
        self.travel_feed = printer.print_speed_mm_s * 60 * 2
        self.print_feed = printer.print_speed_mm_s * 60
        self.filament_mm = 0.0
        self.filament_mm_by_tool: dict[int, float] = {active_tool: 0.0}
        self.travel_mm = 0.0
        self.travel_time_s = 0.0
        self.retraction_time_s = 0.0
        self.active_tool = active_tool
        self._tool_flows: dict[int, float] = {active_tool: flow}
        # A tool starts unprimed so the first deposited segment retains the legacy
        # initial unretract. Tool changes are dormant until select_tool() is called.
        self._tool_primed: dict[int, bool] = {active_tool: False}
        self.x: float | None = None
        self.y: float | None = None
        self.layer_height_mm = printer.layer_height_mm

    def activate_tools(self, flows: dict[int, float]) -> None:
        """Enable exact multi-tool state without changing legacy single-tool output."""
        validated = {_validated_tool_index(tool): flow for tool, flow in flows.items()}
        if self.active_tool not in validated:
            raise ValueError("active tool must be present in activated tool flows")
        if any(not math.isfinite(flow) or flow <= 0 for flow in validated.values()):
            raise ValueError("activated tool flows must be finite and positive")
        self._tool_flows = validated
        self.flow = validated[self.active_tool]
        self.filament_mm_by_tool = {
            tool: self.filament_mm_by_tool.get(tool, 0.0) for tool in validated
        }
        # Firmware tool state is treated as ready at activation; independent state avoids
        # double-unretracting one tool after another tool has moved or been selected.
        self._tool_primed = dict.fromkeys(validated, True)

    def comment(self, text: str) -> None:
        self.lines.append(f"; {text}")

    def raw(self, text: str) -> None:
        self.lines.append(text)

    def set_z(self, z_mm: float, layer_height_mm: float | None = None) -> None:
        if layer_height_mm is not None:
            self.layer_height_mm = layer_height_mm
        self.lines.append(f"G1 Z{z_mm:.3f} F600")

    def _retract_active_tool(self) -> None:
        if not self._tool_primed[self.active_tool]:
            return
        self.lines.append(f"G1 E-{self.retraction_mm:.4f} F{self.retract_feed:.0f}")
        if self.retract_feed > 0:
            self.retraction_time_s += self.retraction_mm / (self.retract_feed / 60)
        self._tool_primed[self.active_tool] = False

    def _prime_active_tool(self) -> None:
        if self._tool_primed[self.active_tool]:
            return
        self.lines.append(f"G1 E{self.retraction_mm:.4f} F{self.retract_feed:.0f}")
        if self.retract_feed > 0:
            self.retraction_time_s += self.retraction_mm / (self.retract_feed / 60)
        self._tool_primed[self.active_tool] = True

    def select_tool(self, tool: int) -> None:
        """Select *tool* once, retaining each tool's independent prime state."""
        tool = _validated_tool_index(tool)
        if tool == self.active_tool:
            return
        self._retract_active_tool()
        self.lines.append(f"T{tool}")
        self.active_tool = tool
        self._tool_primed.setdefault(tool, False)
        self.flow = self._tool_flows.get(tool, self.flow)
        self.filament_mm_by_tool.setdefault(tool, 0.0)

    def _record_deposition(self, e_mm: float) -> None:
        self.filament_mm += e_mm
        self.filament_mm_by_tool[self.active_tool] = (
            self.filament_mm_by_tool.get(self.active_tool, 0.0) + e_mm
        )

    def _travel_to(self, x: float, y: float) -> None:
        self._retract_active_tool()
        if self.x is not None and self.y is not None:
            distance = math.hypot(x - self.x, y - self.y)
            self.travel_mm += distance
            if self.travel_feed > 0:
                self.travel_time_s += distance / (self.travel_feed / 60)
        self.lines.append(f"G1 X{x:.3f} Y{y:.3f} F{self.travel_feed:.0f}")

    def loop(self, points: Sequence[tuple[float, float]], line_width_mm: float) -> None:
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
            self._prime_active_tool()
            e = _extrusion_mm(length, self.layer_height_mm, line_width_mm) * self.flow
            self._record_deposition(e)
            self.lines.append(f"G1 X{x:.3f} Y{y:.3f} E{e:.5f} F{self.print_feed:.0f}")
            px, py = x, y
        self.x, self.y = px, py

    def purge(self, points: Sequence[tuple[float, float]], volume_mm3: float) -> None:
        """Emit an exact physical purge volume, independent of per-tool model flow."""
        if len(points) < 2:
            raise RuntimeError("validated purge segment has no printable path")
        lengths = [
            math.hypot(x - px, y - py) for (px, py), (x, y) in zip(points, points[1:], strict=False)
        ]
        total_length = sum(length for length in lengths if length > 1e-6)
        if total_length <= 1e-6:
            raise RuntimeError("validated purge segment has zero length")

        target_filament_mm = volume_mm3 / _filament_area_mm2()
        self._travel_to(*points[0])
        px, py = points[0]
        emitted_filament_mm = 0.0
        printable_indices = [index for index, length in enumerate(lengths) if length > 1e-6]
        last_printable = printable_indices[-1]
        for index, ((x, y), length) in enumerate(zip(points[1:], lengths, strict=True)):
            if length <= 1e-6:
                continue
            self._prime_active_tool()
            e = (
                target_filament_mm - emitted_filament_mm
                if index == last_printable
                else target_filament_mm * length / total_length
            )
            emitted_filament_mm += e
            self._record_deposition(e)
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


def _placed_on_bed(
    mesh: trimesh.Trimesh, printer: PrinterProfile
) -> tuple[trimesh.Trimesh, bool, np.ndarray]:
    """A copy standing on z=0 and centred on the bed: G-code is in the printer's own
    coordinates (a Marlin origin is the bed's front-left corner), not the model's — a part
    modelled around (0, 0) would otherwise send the head to negative X/Y. Turned 90 degrees
    about Z when it only fits that way, the rule the layer preview already applies.

    A measured shrinkage (the coupon's 60 mm edge) is paid for here, by printing the part
    that much larger in X/Y — before the bed check, since that is the size that must fit."""
    placed = mesh.copy()
    transform = np.eye(4)
    if printer.shrinkage_pct:
        grow = 1.0 / (1.0 - printer.shrinkage_pct / 100.0)
        shrinkage = np.diag([grow, grow, 1.0, 1.0])
        placed.apply_transform(shrinkage)
        transform = shrinkage @ transform
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
        transform = quarter_turn @ transform
        turned = True
    if z > printer.bed_z_mm:
        raise ValueError("model exceeds the printer height; cut it into parts first")
    lo, hi = np.asarray(placed.bounds, dtype=float)
    offset = np.asarray(
        (
            printer.bed_x_mm / 2 - (lo[0] + hi[0]) / 2,
            printer.bed_y_mm / 2 - (lo[1] + hi[1]) / 2,
            -lo[2],
        ),
        dtype=float,
    )
    placed.apply_translation(offset)
    translation = np.eye(4)
    translation[:3, 3] = offset
    return placed, turned, translation @ transform


def _skirt(mesh: trimesh.Trimesh, printer: PrinterProfile, section_z: float) -> Path2:
    """A priming loop SKIRT_GAP_MM outside the first layer's outline (its convex hull, so
    one loop), left out when it would run off the bed."""
    first = _polygons_at(mesh, section_z)
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


def _mouse_ears(
    first_layer: list[Polygon],
    printer: PrinterProfile,
    line_width: float,
    diameter_mm: float,
) -> tuple[list[Path2], int]:
    """Filled first-layer tabs outside sharp convex-hull corners, all inside the bed."""
    if not first_layer or diameter_mm <= 0:
        return [], 0
    solid = unary_union([Polygon(p.exterior) for p in first_layer])
    hull = solid.convex_hull
    if not isinstance(hull, Polygon):
        return [], 0
    coords = list(hull.exterior.coords)[:-1]
    candidates: list[tuple[float, float, float]] = []
    for index, (x, y) in enumerate(coords):
        current = np.asarray((x, y), dtype=float)
        previous = np.asarray(coords[index - 1], dtype=float) - current
        following = np.asarray(coords[(index + 1) % len(coords)], dtype=float) - current
        denominator = float(np.linalg.norm(previous) * np.linalg.norm(following))
        if denominator <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(previous, following) / denominator, -1.0, 1.0))
        angle = math.degrees(math.acos(cosine))
        if angle <= MOUSE_EAR_MAX_CORNER_ANGLE_DEG:
            candidates.append((angle, float(x), float(y)))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    radius = diameter_mm / 2
    paths: list[Path2] = []
    placed = 0
    for _, x, y in candidates[:MAX_MOUSE_EARS]:
        disc = shapely.Point(x, y).buffer(radius, quad_segs=16)
        minx, miny, maxx, maxy = disc.bounds
        if minx < 0 or miny < 0 or maxx > printer.bed_x_mm or maxy > printer.bed_y_mm:
            continue
        parts = [part for part in _as_polygons(disc.difference(solid)) if part.area > line_width**2]
        if not parts:
            continue
        for part in parts:
            paths.append([(round(px, 3), round(py, 3)) for px, py in part.exterior.coords])
            paths.extend(_infill_lines([part], line_width, 0.0))
        placed += 1
    return paths, placed


def _painted_mouse_ears(
    first_layer: list[Polygon],
    printer: PrinterProfile,
    line_width: float,
    diameter_mm: float,
    points_xy: Sequence[tuple[float, float]],
) -> tuple[list[Path2], int]:
    """Build local first-layer tabs at explicit plate-space points painted on the model.

    A picked 3D point is projected to the nearest first-layer boundary only when its XY
    projection is within one tab radius. This keeps a click on an outer wall useful while
    rejecting unrelated top/centre clicks instead of silently moving them to another edge.
    """
    if not first_layer or diameter_mm <= 0:
        return [], 0
    solid = unary_union([Polygon(p.exterior) for p in first_layer])
    if solid.is_empty:
        return [], 0
    radius = diameter_mm / 2
    paths: list[Path2] = []
    centres: list[tuple[float, float]] = []
    for x, y in points_xy:
        requested = shapely.Point(x, y)
        if requested.distance(solid.boundary) > radius + 1e-6:
            continue
        nearest = solid.boundary.interpolate(solid.boundary.project(requested))
        centre = (float(nearest.x), float(nearest.y))
        if any(math.dist(centre, prior) < line_width for prior in centres):
            continue
        disc = shapely.Point(*centre).buffer(radius, quad_segs=16)
        minx, miny, maxx, maxy = disc.bounds
        if minx < 0 or miny < 0 or maxx > printer.bed_x_mm or maxy > printer.bed_y_mm:
            continue
        parts = [part for part in _as_polygons(disc.difference(solid)) if part.area > line_width**2]
        if not parts:
            continue
        for part in parts:
            paths.append([(round(px, 3), round(py, 3)) for px, py in part.exterior.coords])
            paths.extend(_infill_lines([part], line_width, 0.0))
        centres.append(centre)
    return paths, len(centres)


def _adhesion_path_plan(
    mesh: trimesh.Trimesh,
    printer: PrinterProfile,
    first_layer: list[Polygon],
    section_z: float,
    line_width: float,
    effective_adhesion: Literal["skirt", "brim", "mouse_ears", "raft", "none"],
    effective_brim_mm: float,
    mouse_ear_diameter_mm: float,
    mouse_ear_points_mm: Sequence[tuple[float, float, float]],
    placement_transform: np.ndarray,
) -> AdhesionPathPlan:
    """Build non-raft adhesion paths once so collision and emission see identical paths."""

    def freeze(paths: Sequence[Path2]) -> tuple[ImmutablePath2, ...]:
        return tuple(tuple(path) for path in paths)

    if effective_adhesion == "skirt":
        return AdhesionPathPlan(skirt=tuple(_skirt(mesh, printer, section_z)))
    if effective_adhesion == "brim":
        return AdhesionPathPlan(
            brim=freeze(_brim(first_layer, printer, line_width, effective_brim_mm))
        )
    if effective_adhesion != "mouse_ears":
        return AdhesionPathPlan()
    if mouse_ear_points_mm:
        placed_points = trimesh.transform_points(
            np.asarray(mouse_ear_points_mm, dtype=float), placement_transform
        )
        paths, count = _painted_mouse_ears(
            first_layer,
            printer,
            line_width,
            mouse_ear_diameter_mm,
            [(float(point[0]), float(point[1])) for point in placed_points],
        )
    else:
        paths, count = _mouse_ears(
            first_layer,
            printer,
            line_width,
            mouse_ear_diameter_mm,
        )
    return AdhesionPathPlan(mouse_ears=freeze(paths), mouse_ear_count=count)


def _adhesion_blocked_purge_mask(
    candidates: Sequence[Polygon],
    plan: AdhesionPathPlan,
    line_width_mm: float,
) -> int:
    """Return exact candidate collisions for the immutable emitted adhesion paths."""
    clearance = PURGE_TOWER_CLEARANCE_MM + line_width_mm / 2
    blocked = 0
    for path in ((plan.skirt,) if plan.skirt else ()) + plan.brim + plan.mouse_ears:
        if len(path) >= 2:
            blocked |= _blocked_purge_candidate_mask(
                candidates,
                LineString(path),
                clearance,
            )
    return blocked


def _process_region_at_layer(
    region: paint.Region, placement_transform: np.ndarray, sample_z: float
) -> BaseGeometry:
    """Return one exact plate-space XY footprint for a supported model-space region."""
    if isinstance(region, paint.BoxRegion):
        low = np.asarray(region.min_mm, dtype=float)
        high = np.asarray(region.max_mm, dtype=float)
        corners = np.asarray(
            [
                (x, y, z)
                for x in (low[0], high[0])
                for y in (low[1], high[1])
                for z in (low[2], high[2])
            ],
            dtype=float,
        )
        placed = trimesh.transform_points(corners, placement_transform)
        if sample_z < placed[:, 2].min() - 1e-6 or sample_z > placed[:, 2].max() + 1e-6:
            return Polygon()
        return shapely.box(
            float(placed[:, 0].min()),
            float(placed[:, 1].min()),
            float(placed[:, 0].max()),
            float(placed[:, 1].max()),
        )
    if region.axis != "z":
        return Polygon()
    half = region.depth_mm / 2
    depth_points = trimesh.transform_points(
        np.asarray(
            [
                (region.points_mm[0][0], region.points_mm[0][1], region.offset_mm - half),
                (region.points_mm[0][0], region.points_mm[0][1], region.offset_mm + half),
            ],
            dtype=float,
        ),
        placement_transform,
    )
    if sample_z < depth_points[:, 2].min() - 1e-6 or sample_z > depth_points[:, 2].max() + 1e-6:
        return Polygon()
    placed = trimesh.transform_points(
        np.asarray([(x, y, region.offset_mm) for x, y in region.points_mm], dtype=float),
        placement_transform,
    )
    footprint = Polygon([(float(point[0]), float(point[1])) for point in placed])
    return footprint if footprint.is_valid and footprint.area > 1e-6 else Polygon()


def _planned_tool_layers(
    layer_footprints: Sequence[BaseGeometry],
    layers: Sequence[LayerPlan],
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    base_tool: int,
) -> tuple[tuple[int, ...], ...]:
    """Build one deterministic, future tool order without emitting machine commands.

    Each changed layer starts and ends on the explicit base tool. Assigned tools follow
    last-painted-wins order, matching process-region resolution, and repeat assignments to
    one tool collapse into one visit. The plan is deliberately conservative: even a region
    covering a whole layer still reserves the return to base until real path grouping proves
    that return unnecessary.
    """
    assigned = [modifier for modifier in modifiers if modifier.material_slot is not None]
    planned: list[tuple[int, ...]] = []
    for footprint, layer in zip(layer_footprints, layers, strict=True):
        claimed: BaseGeometry = Polygon()
        tools: list[int] = []
        for modifier in reversed(assigned):
            region = _process_region_at_layer(modifier.region, placement_transform, layer.sample_z)
            active = footprint.intersection(region).difference(claimed)
            if active.is_empty or active.area <= 1e-6:
                continue
            claimed = claimed.union(active)
            assert modifier.material_slot is not None
            tool = modifier.material_slot
            if tool != base_tool and tool not in tools:
                tools.append(tool)
        planned.append((base_tool, *tools, base_tool) if tools else (base_tool,))
    return tuple(planned)


def _material_path_counts(
    paths: Sequence[Path2],
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
    base_tool: int,
    tool_areas: MaterialToolAreas | None = None,
) -> dict[int, int]:
    """Count exact path pieces assigned to each tool without emitting tool commands.

    The same last-painted-wins geometry used by local process overrides is applied to the
    paths that will actually be written. A path crossing a material boundary contributes
    one piece to each affected tool, matching the boundary split used by emitted batches.
    """
    return {
        tool: len(pieces)
        for tool, pieces in _material_path_pieces(
            paths,
            modifiers,
            placement_transform,
            sample_z,
            base_tool,
            tool_areas,
        ).items()
    }


def _material_path_pieces(
    paths: Sequence[Path2],
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
    base_tool: int,
    tool_areas: MaterialToolAreas | None = None,
) -> dict[int, list[Path2]]:
    """Split real extrusion paths into disjoint, last-painted-wins tool pieces."""
    assigned = [modifier for modifier in modifiers if modifier.material_slot is not None]
    if not paths:
        return {}
    if not assigned:
        return {base_tool: list(paths)}

    if tool_areas is None:
        tool_areas = _material_tool_areas(assigned, placement_transform, sample_z)
    claimed = unary_union([area for _, area in tool_areas])
    pieces_by_tool: dict[int, list[Path2]] = {}

    def add(tool: int, geometry: BaseGeometry) -> None:
        for piece in _as_lines(geometry):
            if piece.length <= 1e-6:
                continue
            pieces_by_tool.setdefault(tool, []).append(
                [(round(x, 3), round(y, 3)) for x, y in piece.coords]
            )

    for path in paths:
        line = LineString(path)
        if line.length <= 1e-6:
            continue
        for tool, area in tool_areas:
            add(tool, line.intersection(area))
        add(base_tool, line.difference(claimed))
    return pieces_by_tool


def _material_tool_areas(
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
) -> MaterialToolAreas:
    """Resolve disjoint last-painted-wins material areas once for one layer."""
    claimed: BaseGeometry = Polygon()
    areas: list[tuple[int, BaseGeometry]] = []
    for modifier in reversed(modifiers):
        if modifier.material_slot is None:
            continue
        area = _process_region_at_layer(modifier.region, placement_transform, sample_z).difference(
            claimed
        )
        if area.is_empty:
            continue
        areas.append((modifier.material_slot, area))
        claimed = claimed.union(area)
    return tuple(areas)


def _queue_material_paths(
    batches: list[MaterialPathBatch],
    counts: MaterialPathCounts,
    kind: str,
    comment: str,
    paths: Sequence[Path2],
    line_width_mm: float,
    nearest_first: bool,
    settings: SliceSettings,
    placement_transform: np.ndarray,
    sample_z: float,
    tool_areas: MaterialToolAreas,
    modifier: ProcessModifier | None = None,
) -> None:
    for tool, pieces in _material_path_pieces(
        paths,
        settings.process_modifiers,
        placement_transform,
        sample_z,
        settings.base_tool,
        tool_areas,
    ).items():
        per_kind = counts.setdefault(tool, {})
        per_kind[kind] = per_kind.get(kind, 0) + len(pieces)
        batches.append(
            MaterialPathBatch(
                tool=tool,
                kind=kind,
                comment=comment,
                paths=tuple(pieces),
                line_width_mm=line_width_mm,
                nearest_first=nearest_first,
                modifier=modifier,
            )
        )


def _ordered_material_tools(
    candidate_tools: Sequence[int],
    counts: MaterialPathCounts,
    base_tool: int,
    preferred_tools: Sequence[int],
) -> tuple[int, ...]:
    actual_tools = {tool for tool, kinds in counts.items() if any(kinds.values())}
    ordered_candidates = dict.fromkeys((*candidate_tools, *preferred_tools))
    assigned = [tool for tool in ordered_candidates if tool != base_tool and tool in actual_tools]
    return (base_tool, *assigned, base_tool) if assigned else (base_tool,)


def _bind_purge_plan_to_paths(
    candidate: PurgePlan,
    layer_counts: Sequence[MaterialPathCounts],
    base_tool: int,
    preferred_tools: Sequence[int],
) -> PurgePlan:
    """Narrow the geometric candidate to tools with real model/support path pieces."""
    exact_layers: list[tuple[int, ...]] = []
    for candidate_tools, counts in zip(candidate.layer_tools, layer_counts, strict=True):
        exact_layers.append(
            _ordered_material_tools(candidate_tools, counts, base_tool, preferred_tools)
        )
    layer_tools = tuple(exact_layers)
    has_changes = any(len(tools) > 1 for tools in layer_tools)
    return PurgePlan(layer_tools, candidate.tower if has_changes else None)


def _requires_material_preflight(
    preferred_tools: Sequence[int],
    base_tool: int,
) -> bool:
    """Use two passes only when a painted assignment can produce a real tool change."""
    return any(tool != base_tool for tool in preferred_tools)


def _purge_tower_centerline(
    tower: Polygon,
    line_width_mm: float,
    layer_index: int,
) -> LineString:
    """Build an inset, layer-alternating serpentine in the reserved square.

    Even layers use X-major runs and odd layers use Y-major runs.  Keeping this
    independent of the writer makes the future deposited geometry inspectable without
    accidentally activating purge extrusion.
    """
    if not math.isfinite(line_width_mm):
        raise ValueError("purge tower line width must be finite")
    if line_width_mm <= 0 or tower.is_empty:
        return LineString()
    min_x, min_y, max_x, max_y = tower.bounds
    if not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y)):
        raise ValueError("purge tower bounds must be finite")
    inset = line_width_mm / 2
    low_x, high_x = min_x + inset, max_x - inset
    low_y, high_y = min_y + inset, max_y - inset
    if high_x < low_x - 1e-12 or high_y < low_y - 1e-12:
        return LineString()

    x_major = layer_index % 2 == 0
    cross_low, cross_high = (low_y, high_y) if x_major else (low_x, high_x)
    cross_span = max(0.0, cross_high - cross_low)
    step_count = max(0, math.floor(cross_span / line_width_mm + 1e-9))
    cross_coordinates = [cross_low + index * line_width_mm for index in range(step_count + 1)]
    # Land on a numerically coincident far edge instead of producing a duplicate run.
    if cross_coordinates and math.isclose(
        cross_coordinates[-1], cross_high, rel_tol=0.0, abs_tol=1e-9
    ):
        cross_coordinates[-1] = cross_high

    points: list[tuple[float, float]] = []
    for index, cross in enumerate(cross_coordinates):
        along_low, along_high = (
            ((low_x, high_x) if index % 2 == 0 else (high_x, low_x))
            if x_major
            else ((low_y, high_y) if index % 2 == 0 else (high_y, low_y))
        )
        run = (
            [(along_low, cross), (along_high, cross)]
            if x_major
            else [(cross, along_low), (cross, along_high)]
        )
        if not points:
            points.extend(run)
        else:
            points.append(run[0])
            points.append(run[1])
    if len(points) < 2 or all(point == points[0] for point in points[1:]):
        return LineString()
    return LineString(points)


def _purge_tower_capacity_mm3(
    centerline: LineString,
    layer_height_mm: float,
    line_width_mm: float,
) -> float:
    """Return capacity from generated line length, never from tower area."""
    if not math.isfinite(layer_height_mm) or not math.isfinite(line_width_mm):
        raise ValueError("purge tower layer height and line width must be finite")
    if layer_height_mm <= 0 or line_width_mm <= 0 or centerline.is_empty:
        return 0.0
    return float(centerline.length) * layer_height_mm * line_width_mm


def _purge_tower_segments(
    centerline: LineString,
    layer_height_mm: float,
    line_width_mm: float,
    transition_volumes_mm3: Sequence[float],
) -> PurgeTowerLayerSegments:
    """Split one centerline into a base and one exact-length segment per transition."""
    volumes = tuple(float(volume) for volume in transition_volumes_mm3)
    if any(not math.isfinite(volume) or volume < 0 for volume in volumes):
        raise ValueError("purge transition volumes must be finite and non-negative")
    capacity = _purge_tower_capacity_mm3(centerline, layer_height_mm, line_width_mm)
    required_volume = sum(volumes)
    volume_tolerance = max(1e-9, capacity * 1e-12)
    if required_volume > capacity + volume_tolerance:
        raise ValueError(
            "purge volume exceeds the tower capacity on one layer; "
            "increase tower width or reduce purge per change"
        )
    if layer_height_mm <= 0 or line_width_mm <= 0:
        empty = LineString()
        return PurgeTowerLayerSegments(centerline, empty, tuple(empty for _ in volumes))

    required_lengths = [volume / (layer_height_mm * line_width_mm) for volume in volumes]
    available_length = float(centerline.length)
    purge_length = min(sum(required_lengths), available_length)
    structural_end = max(0.0, available_length - purge_length)

    def section(start: float, end: float) -> LineString:
        if end - start <= 1e-12 or centerline.is_empty:
            return LineString()
        geometry = substring(centerline, start, min(end, available_length))
        return geometry if isinstance(geometry, LineString) else LineString()

    structural = section(0.0, structural_end)
    purge: list[LineString] = []
    cursor = structural_end
    for required_length in required_lengths:
        end = cursor + required_length
        purge.append(section(cursor, end))
        cursor = end
    return PurgeTowerLayerSegments(centerline, structural, tuple(purge))


def _purge_tower_candidates(
    printer: PrinterProfile,
    width_mm: float,
) -> tuple[Polygon, ...]:
    """Return the four bed-corner candidates in stable preference order."""
    low_x = PURGE_TOWER_EDGE_MARGIN_MM
    low_y = PURGE_TOWER_EDGE_MARGIN_MM
    high_x = printer.bed_x_mm - PURGE_TOWER_EDGE_MARGIN_MM - width_mm
    high_y = printer.bed_y_mm - PURGE_TOWER_EDGE_MARGIN_MM - width_mm
    if high_x < low_x or high_y < low_y:
        return ()
    return tuple(
        shapely.box(x, y, x + width_mm, y + width_mm)
        for x, y in (
            (high_x, high_y),
            (low_x, high_y),
            (high_x, low_y),
            (low_x, low_y),
        )
    )


def _blocked_purge_candidate_mask(
    candidates: Sequence[Polygon],
    geometry: BaseGeometry,
    clearance_mm: float,
) -> int:
    """Return one compact bit per candidate whose exact geometry is too close."""
    if geometry.is_empty:
        return 0
    return sum(
        1 << index
        for index, candidate in enumerate(candidates)
        if candidate.distance(geometry) <= clearance_mm + 1e-9
    )


def _blocked_purge_path_mask(
    candidates: Sequence[Polygon],
    batches: Sequence[MaterialPathBatch],
) -> int:
    """Collide candidate solids with the deposited bead of every model/support path."""
    blocked = 0
    for batch in batches:
        clearance = PURGE_TOWER_CLEARANCE_MM + batch.line_width_mm / 2
        for path in batch.paths:
            if len(path) < 2:
                continue
            blocked |= _blocked_purge_candidate_mask(
                candidates,
                LineString(path),
                clearance,
            )
            if blocked == (1 << len(candidates)) - 1:
                return blocked
    return blocked


def _reserve_purge_tower(
    candidates: Sequence[Polygon],
    blocked_candidate_mask: int,
) -> Polygon:
    """Reserve the first exact, collision-free candidate or fail before the writer."""
    if not candidates:
        raise ValueError("purge tower does not fit inside the printer bed")
    for index, tower in enumerate(candidates):
        if not blocked_candidate_mask & (1 << index):
            return tower
    raise ValueError(
        "purge tower has no collision-free bed position; reduce the model or tower width"
    )


def _purge_plan(
    settings: SliceSettings,
    layer_footprints: Sequence[BaseGeometry],
    layers: Sequence[LayerPlan],
    placement_transform: np.ndarray,
) -> PurgePlan:
    if settings.tool_change_mode != "marlin_tn":
        return PurgePlan(tuple((settings.base_tool,) for _ in layers), None)
    layer_tools = _planned_tool_layers(
        layer_footprints,
        layers,
        settings.process_modifiers,
        placement_transform,
        settings.base_tool,
    )
    return PurgePlan(layer_tools, None)


def _local_infill_areas(
    sparse_area: list[Polygon],
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
) -> tuple[list[Polygon], list[tuple[list[Polygon], ProcessModifier]]]:
    """Partition sparse infill with deterministic last-painted-wins local overrides."""
    if not modifiers:
        return sparse_area, []
    remaining: BaseGeometry = unary_union(sparse_area)
    claimed: BaseGeometry = Polygon()
    local: list[tuple[list[Polygon], ProcessModifier]] = []
    for modifier in reversed(modifiers):
        footprint = _process_region_at_layer(modifier.region, placement_transform, sample_z)
        area = remaining.intersection(footprint).difference(claimed)
        parts = _as_polygons(area)
        if parts:
            local.append((parts, modifier))
            claimed = claimed.union(area)
    return _as_polygons(remaining.difference(claimed)), local


def _locally_modified_perimeters(
    polygon: Polygon,
    nozzle_mm: float,
    wall_count: int,
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
) -> tuple[list[Path2], list[tuple[list[Path2], ProcessModifier]], list[Polygon]]:
    """Clip perimeter passes and their inner fill boundary by local wall-count regions.

    Density, speed and pattern paint must not introduce seams into otherwise continuous
    perimeters. Where a wall override is present, the outer pass remains because both
    global and local contracts require at least one wall. Last painted wins, matching
    local infill.
    """
    wall_modifiers = [
        modifier
        for modifier in modifiers
        if modifier.wall_count is not None and modifier.wall_count != wall_count
    ]
    if not wall_modifiers:
        rings, infill = _perimeter_rings(polygon, nozzle_mm, wall_count)
        return rings, [], infill

    claimed: BaseGeometry = Polygon()
    local_areas: list[tuple[BaseGeometry, ProcessModifier]] = []
    for modifier in reversed(wall_modifiers):
        footprint = _process_region_at_layer(modifier.region, placement_transform, sample_z)
        area = polygon.intersection(footprint).difference(claimed)
        if not area.is_empty:
            local_areas.append((area, modifier))
            claimed = claimed.union(area)
    base_area = polygon.difference(claimed)
    cache: dict[int, tuple[list[Path2], list[Polygon]]] = {}

    def paths_for(area: BaseGeometry, count: int) -> tuple[list[Path2], list[Polygon]]:
        if count not in cache:
            cache[count] = _perimeter_rings(polygon, nozzle_mm, count)
        rings, infill = cache[count]
        clipped_paths: list[Path2] = []
        for ring in rings:
            for piece in _as_lines(LineString(ring).intersection(area)):
                if piece.length > 1e-6:
                    clipped_paths.append([(round(x, 3), round(y, 3)) for x, y in piece.coords])
        clipped_infill = _as_polygons(unary_union(infill).intersection(area))
        return clipped_paths, clipped_infill

    base_paths, infill_parts = paths_for(base_area, wall_count)
    local_paths: list[tuple[list[Path2], ProcessModifier]] = []
    for area, modifier in local_areas:
        assert modifier.wall_count is not None
        paths, local_infill = paths_for(area, modifier.wall_count)
        local_paths.append((paths, modifier))
        infill_parts.extend(local_infill)
    return base_paths, local_paths, _as_polygons(unary_union(infill_parts))


def _locally_modified_speed_paths(
    paths: Sequence[Path2],
    modifiers: Sequence[ProcessModifier],
    placement_transform: np.ndarray,
    sample_z: float,
) -> tuple[list[Path2], list[tuple[list[Path2], ProcessModifier]]]:
    """Split paths by local speed/temperature without changing their geometry."""
    speed_modifiers = [
        modifier
        for modifier in modifiers
        if modifier.print_speed_pct != 100 or modifier.nozzle_temperature_offset_c != 0
    ]
    if not speed_modifiers:
        return list(paths), []

    claimed: BaseGeometry = Polygon()
    local_areas: list[tuple[BaseGeometry, ProcessModifier]] = []
    for modifier in reversed(speed_modifiers):
        footprint = _process_region_at_layer(modifier.region, placement_transform, sample_z)
        area = footprint.difference(claimed)
        if not area.is_empty:
            local_areas.append((area, modifier))
            claimed = claimed.union(area)

    base_paths: list[Path2] = []
    local_paths: list[tuple[list[Path2], ProcessModifier]] = [
        ([], modifier) for _, modifier in local_areas
    ]
    for path in paths:
        line = LineString(path)
        for piece in _as_lines(line.difference(claimed)):
            if piece.length > 1e-6:
                base_paths.append([(round(x, 3), round(y, 3)) for x, y in piece.coords])
        for index, (area, _) in enumerate(local_areas):
            for piece in _as_lines(line.intersection(area)):
                if piece.length > 1e-6:
                    local_paths[index][0].append(
                        [(round(x, 3), round(y, 3)) for x, y in piece.coords]
                    )
    return base_paths, [(pieces, modifier) for pieces, modifier in local_paths if pieces]


def _temperatures(settings: SliceSettings) -> tuple[float, float]:
    nozzle_c, bed_c = PRINT_TEMPS_C.get(settings.material_id, PRINT_TEMPS_C["pla"])
    return (
        max(nozzle_c + settings.tuning.nozzle_offset_c, MIN_NOZZLE_C),
        max(bed_c + settings.tuning.bed_offset_c, 0.0),
    )


def _thermal_plan(settings: SliceSettings, purge_plan: PurgePlan) -> ThermalPlan:
    """Bind temperatures only to tools retained by exact material-path preflight."""
    material_by_tool: dict[int, str] = {}
    for modifier in settings.process_modifiers:
        if modifier.material_slot is None:
            continue
        assert modifier.material_id is not None
        previous = material_by_tool.setdefault(modifier.material_slot, modifier.material_id)
        if previous != modifier.material_id:
            raise ValueError(
                f"material slot T{modifier.material_slot} has conflicting material ids: "
                f"{previous} and {modifier.material_id}"
            )

    base_material = material_by_tool.get(settings.base_tool)
    if base_material is not None and base_material != settings.material_id:
        raise ValueError(
            f"base material slot T{settings.base_tool} must use {settings.material_id}, "
            f"not {base_material}"
        )

    ordered_tools = tuple(
        dict.fromkeys(
            (settings.base_tool, *(tool for tools in purge_plan.layer_tools for tool in tools))
        )
    )
    base_nozzle_c, bed_c = _temperatures(settings)
    targets = [ToolThermalTarget(settings.base_tool, settings.material_id, base_nozzle_c)]
    for tool in ordered_tools:
        if tool == settings.base_tool:
            continue
        material_id = material_by_tool.get(tool)
        if material_id is None:
            raise ValueError(f"used tool T{tool} has no material mapping")
        catalog_temperatures = PRINT_TEMPS_C.get(material_id)
        if catalog_temperatures is None:
            raise ValueError(f"used tool T{tool} material {material_id!r} has no print temperature")
        targets.append(ToolThermalTarget(tool, material_id, catalog_temperatures[0]))
    return ThermalPlan(settings.base_tool, bed_c, tuple(targets))


def _begin_local_process(
    writer: _Writer,
    modifier: ProcessModifier,
    active_tool_nozzle_c: float,
) -> float:
    previous_feed = writer.print_feed
    writer.print_feed = previous_feed * (modifier.print_speed_pct / 100.0)
    if modifier.nozzle_temperature_offset_c != 0:
        local_nozzle_c = max(
            active_tool_nozzle_c + modifier.nozzle_temperature_offset_c, MIN_NOZZLE_C
        )
        writer.lines.append(f"M104 S{local_nozzle_c:g}")
    return previous_feed


def _local_temperature_label(modifier: ProcessModifier) -> str:
    if modifier.nozzle_temperature_offset_c == 0:
        return ""
    return f" temperature_offset={modifier.nozzle_temperature_offset_c:+g}C"


def _end_local_process(
    writer: _Writer,
    modifier: ProcessModifier,
    active_tool_nozzle_c: float,
    previous_feed: float,
) -> None:
    if modifier.nozzle_temperature_offset_c != 0:
        writer.lines.append(f"M104 S{active_tool_nozzle_c:g}")
    writer.print_feed = previous_feed


def _emit_material_tool_batches(
    writer: _Writer,
    batches: Sequence[MaterialPathBatch],
    plan: LayerMaterialPlan,
    tool: int,
    layer_index: int,
    thermal_plan: ThermalPlan,
    here: Callable[[], tuple[float, float]],
) -> None:
    tool_batches = [batch for batch in batches if batch.tool == tool]
    if not tool_batches:
        return
    if len(plan.tool_order) > 1:
        groups = ",".join(
            f"{kind}:{piece_count}" for kind, piece_count in sorted(plan.counts[tool].items())
        )
        writer.comment(
            f"material-path-batch: layer={layer_index + 1} tool=T{tool} "
            f"groups={groups} switching=enabled"
        )
    for batch in tool_batches:
        writer.comment(batch.comment)
        active_tool_nozzle_c = thermal_plan.nozzle_c_for(writer.active_tool)
        previous_feed = (
            _begin_local_process(writer, batch.modifier, active_tool_nozzle_c)
            if batch.modifier is not None
            else None
        )
        batch_paths = list(batch.paths)
        if batch.nearest_first:
            batch_paths = _nearest_first(batch_paths, here())
        for path in batch_paths:
            writer.loop(path, batch.line_width_mm)
        if batch.modifier is not None:
            assert previous_feed is not None
            _end_local_process(writer, batch.modifier, active_tool_nozzle_c, previous_feed)


def _raft_paths(
    first_layer: list[Polygon],
    printer: PrinterProfile,
    line_width: float,
    margin_mm: float,
    base_density_pct: float = 40.0,
    interface_density_pct: float = 100.0,
    base_angle_deg: float = 0.0,
    interface_angle_deg: float = 90.0,
) -> tuple[list[Path2], list[Path2]]:
    """One sparse base pattern and one dense interface pattern for a removable raft."""
    if not first_layer:
        raise ValueError("raft requires a non-empty first layer")
    solid = unary_union([Polygon(p.exterior) for p in first_layer]).buffer(
        margin_mm, join_style="round"
    )
    minx, miny, maxx, maxy = solid.bounds
    if minx < 0 or miny < 0 or maxx > printer.bed_x_mm or maxy > printer.bed_y_mm:
        raise ValueError("raft exceeds the printer bed; reduce its margin or cut the model")

    base: list[Path2] = []
    interface: list[Path2] = []
    for area in _as_polygons(solid):
        rings, infill_area = _perimeter_rings(area, line_width, 1)
        base.extend(rings)
        base.extend(
            _infill_lines(
                infill_area,
                line_width * 100.0 / base_density_pct,
                base_angle_deg,
            )
        )
        interface.extend(rings)
        interface.extend(
            _infill_lines(
                infill_area,
                line_width * 100.0 / interface_density_pct,
                interface_angle_deg,
            )
        )
    return base, interface


def _header(
    printer: PrinterProfile,
    settings: SliceSettings,
    layers: list[LayerPlan],
    total_layers: int,
    thermal_plan: ThermalPlan,
    tool_switching_active: bool = False,
) -> list[str]:
    nozzle_c = thermal_plan.nozzle_c_for(thermal_plan.base_tool)
    bed_c = thermal_plan.bed_c
    layer_height = (
        f"adaptive min_layer={min(layer.height_mm for layer in layers):g}mm "
        f"max_layer={max(layer.height_mm for layer in layers):g}mm"
        if settings.adaptive_layer_height
        else f"{printer.layer_height_mm:g}mm"
    )
    material_assignments = sum(
        modifier.material_slot is not None for modifier in settings.process_modifiers
    )
    material_contract = (
        f" material_assignments={material_assignments} "
        f"tool_change_mode={settings.tool_change_mode} tool_count={settings.tool_count} "
        f"base_tool=T{settings.base_tool} "
        f"purge_tower={'planned' if settings.purge_tower_enabled else 'disabled'} "
        f"purge_tower_width={settings.purge_tower_width_mm:g}mm "
        f"purge_per_change={settings.purge_volume_mm3:g}mm3 "
        f"tool_switching={'enabled' if tool_switching_active else 'disabled'}"
        if material_assignments
        else ""
    )
    lines = [
        f"; generated by Physical AI 3D slicer v1 for {printer.name}",
        f"; material={settings.material_id} layer_height={layer_height} "
        f"nozzle={printer.nozzle_mm:g}mm infill={settings.infill_density_pct:g}% "
        f"walls={settings.wall_count} top_layers={settings.top_solid_layers} "
        f"bottom_layers={settings.bottom_solid_layers} supports={settings.supports} "
        f"support_type={settings.support_type} "
        f"support_generation_mode={settings.support_generation_mode} "
        f"support_modifiers={len(settings.support_modifiers)} "
        f"process_modifiers={len(settings.process_modifiers)}{material_contract} "
        f"adhesion={settings.adhesion_mode}",
        f"; layers={total_layers}",
        f"M140 S{bed_c:g}",
    ]
    if tool_switching_active:
        lines.append(f"T{thermal_plan.base_tool}")
    lines.extend(
        [
            f"M104 S{nozzle_c:g}",
            "G28",
            f"M190 S{bed_c:g}",
            f"M109 S{nozzle_c:g}",
            "G21",
            "G90",
            "M83",
            "G92 E0",
        ]
    )
    return lines


def _footer(thermal_plan: ThermalPlan | None = None) -> list[str]:
    nozzle_off = (
        [f"M104 T{tool} S0" for tool in thermal_plan.used_tools]
        if thermal_plan is not None
        else ["M104 S0"]
    )
    return [*nozzle_off, "M140 S0", "G91", "G1 Z5 F600", "G90", "M84"]


def slice_mesh(
    mesh: trimesh.Trimesh, printer: PrinterProfile, settings: SliceSettings
) -> tuple[str, SliceStats]:
    if printer.technology != "fdm":
        raise ValueError("G-code generation currently supports FDM printers only")
    if not math.isfinite(printer.print_speed_mm_s) or printer.print_speed_mm_s <= 0:
        raise ValueError("print speed must be finite and greater than zero")
    if mesh.is_empty or not mesh.is_watertight:
        raise ValueError("repair the mesh into a closed solid before slicing")
    if printer.layer_height_mm <= 0 or printer.layer_height_mm > printer.nozzle_mm * 0.8:
        raise ValueError("layer height must be at most 80% of the nozzle diameter")
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    if not np.isfinite(bounds).all() or (extents <= 0).any():
        raise ValueError("mesh bounds are invalid")
    support_faces: np.ndarray | None = None
    blocked_support_faces = 0
    enforced_support_faces = 0
    if settings.supports:
        support_faces, blocked_support_faces, enforced_support_faces = _support_face_selection(
            mesh,
            printer,
            settings.support_modifiers,
            settings.support_generation_mode,
        )
    mesh, turned, placement_transform = _placed_on_bed(mesh, printer)
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    layers = _layer_plan(mesh, printer, settings)
    raft_enabled = settings.adhesion_mode == "raft"
    raft_layer_count = (
        settings.raft_base_layers + settings.raft_interface_layers if raft_enabled else 0
    )
    raft_base_layer_height_mm = settings.raft_base_layer_height_mm or printer.layer_height_mm
    raft_interface_layer_height_mm = (
        settings.raft_interface_layer_height_mm or printer.layer_height_mm
    )
    if raft_enabled and (
        raft_base_layer_height_mm > printer.nozzle_mm * 0.8
        or raft_interface_layer_height_mm > printer.nozzle_mm * 0.8
    ):
        raise ValueError("raft layer height must be at most 80% of the nozzle diameter")
    raft_total_height_mm = (
        settings.raft_base_layers * raft_base_layer_height_mm
        + settings.raft_interface_layers * raft_interface_layer_height_mm
        if raft_enabled
        else 0.0
    )
    if (
        raft_enabled
        and layers[-1].machine_z + raft_total_height_mm + settings.raft_air_gap_mm
        > printer.bed_z_mm
    ):
        raise ValueError("model and raft exceed the printer height; cut it into parts first")
    total_layers = len(layers) + raft_layer_count
    if total_layers > MAX_LAYERS:
        raise ValueError("too many layers; use a larger layer height")

    line_width = printer.nozzle_mm
    density = max(settings.infill_density_pct, 0.0)
    spacing = line_width / (density / 100.0) if density > 0 else 0.0
    support_pts: Supports | TreeSupports
    if not settings.supports:
        support_pts = Supports([])
    elif settings.support_type == "tree":
        support_pts = _tree_supports(mesh, printer, unsupported_faces=support_faces)
    else:
        support_pts = _support_columns(mesh, printer, unsupported_faces=support_faces)
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
    layer_polygons: list[list[Polygon]] = []
    for index, layer in enumerate(layers):
        section_z = layer.sample_z
        pull_in = printer.xy_compensation_mm + (tuning.elephant_foot_mm if index == 0 else 0.0)
        layer_polygons.append(_compensated(_polygons_at(mesh, section_z), pull_in))
    layer_footprints: list[BaseGeometry] = [
        unary_union(polygons) if polygons else Polygon() for polygons in layer_polygons
    ]

    learned = tuning.changes()

    effective_brim_mm = (
        settings.brim_width_mm
        if settings.adhesion_mode == "brim"
        else tuning.brim_mm
        if settings.adhesion_mode == "auto"
        else 0.0
    )
    print_skirt = settings.adhesion_mode == "skirt" or (
        settings.adhesion_mode == "auto" and settings.skirt and effective_brim_mm <= 0
    )
    effective_adhesion: Literal["skirt", "brim", "mouse_ears", "raft", "none"] = (
        "raft"
        if raft_enabled
        else "mouse_ears"
        if settings.adhesion_mode == "mouse_ears"
        else "brim"
        if effective_brim_mm > 0
        else "skirt"
        if print_skirt
        else "none"
    )
    raft_height_detail = (
        f" base_height={raft_base_layer_height_mm:g}mm"
        f" interface_height={raft_interface_layer_height_mm:g}mm"
        if settings.raft_base_layer_height_mm is not None
        or settings.raft_interface_layer_height_mm is not None
        else ""
    )
    adhesion_detail = (
        f" margin={settings.raft_margin_mm:g}mm layers={raft_layer_count}"
        f" base_layers={settings.raft_base_layers}"
        f" interface_layers={settings.raft_interface_layers}"
        + raft_height_detail
        + f" gap={settings.raft_air_gap_mm:g}mm"
        f" base_density={settings.raft_base_density_pct:g}%"
        f" interface_density={settings.raft_interface_density_pct:g}%"
        f" density_source={'profile' if settings.raft_density_profiled else 'fallback'}"
        + (
            f" base_speed={settings.raft_base_speed_pct:g}%"
            f" interface_speed={settings.raft_interface_speed_pct:g}%"
            if settings.raft_base_speed_pct != 100 or settings.raft_interface_speed_pct != 100
            else ""
        )
        if effective_adhesion == "raft"
        else (
            f" diameter={settings.mouse_ear_diameter_mm:g}mm"
            + (
                f" painted_points={len(settings.mouse_ear_points_mm)}"
                if settings.mouse_ear_points_mm
                else ""
            )
        )
        if effective_adhesion == "mouse_ears"
        else f" width={effective_brim_mm:g}mm"
        if effective_brim_mm > 0
        else ""
    )
    purge_plan_candidate = _purge_plan(
        settings,
        layer_footprints,
        layers,
        placement_transform,
    )
    # Far behind the part (+Y), centred: the nearest corner of every loop is its rearmost.
    seam_anchor = (
        float(bounds[0][0] + extents[0] / 2),
        float(bounds[1][1] + 10 * max(float(extents[0]), float(extents[1]))),
    )
    purge_tower_candidates = _purge_tower_candidates(printer, settings.purge_tower_width_mm)
    adhesion_plan = _adhesion_path_plan(
        mesh,
        printer,
        layer_polygons[0],
        layers[0].sample_z,
        line_width,
        effective_adhesion,
        effective_brim_mm,
        settings.mouse_ear_diameter_mm,
        settings.mouse_ear_points_mm,
        placement_transform,
    )

    brim_loops = 0
    mouse_ear_count = adhesion_plan.mouse_ear_count
    solid_skin_paths = 0
    process_modified_layers: set[int] = set()
    layer_material_plans: list[LayerMaterialPlan] = []
    preferred_material_tools = tuple(
        dict.fromkeys(
            modifier.material_slot
            for modifier in reversed(settings.process_modifiers)
            if modifier.material_slot is not None
        )
    )

    def build_layer_material_paths(
        index: int,
    ) -> tuple[
        tuple[MaterialPathBatch, ...],
        MaterialPathCounts,
        tuple[int, ...],
        int,
        bool,
        int,
    ]:
        layer = layers[index]
        section_z = layer.sample_z
        polygons = layer_polygons[index]
        layer_material_counts: MaterialPathCounts = {}
        layer_material_batches: list[MaterialPathBatch] = []
        layer_solid_skin_paths = 0
        layer_process_modified = False
        layer_material_tool_areas = _material_tool_areas(
            settings.process_modifiers,
            placement_transform,
            section_z,
        )

        def queue_material_paths(
            kind: str,
            comment: str,
            paths: Sequence[Path2],
            path_width_mm: float = line_width,
            nearest_first: bool = True,
            modifier: ProcessModifier | None = None,
        ) -> None:
            _queue_material_paths(
                layer_material_batches,
                layer_material_counts,
                kind,
                comment,
                paths,
                path_width_mm,
                nearest_first,
                settings,
                placement_transform,
                section_z,
                layer_material_tool_areas,
                modifier,
            )

        angle = 0.0 if index % 2 == 0 else 90.0
        for polygon in polygons:
            rings, local_rings, infill_area = _locally_modified_perimeters(
                polygon,
                line_width,
                settings.wall_count,
                settings.process_modifiers,
                placement_transform,
                section_z,
            )
            rings, speed_rings = _locally_modified_speed_paths(
                rings, settings.process_modifiers, placement_transform, section_z
            )
            queue_material_paths(
                "perimeter",
                "TYPE:perimeter",
                [_seam_first(ring, seam_anchor) for ring in rings],
                nearest_first=False,
            )
            for speed_paths, modifier in speed_rings:
                queue_material_paths(
                    "perimeter",
                    f"TYPE:local-perimeter walls={settings.wall_count} "
                    f"speed={modifier.print_speed_pct:g}%"
                    f"{_local_temperature_label(modifier)}",
                    speed_paths,
                    modifier=modifier,
                )
            for local_paths, modifier in local_rings:
                local_paths, local_speed_paths = _locally_modified_speed_paths(
                    local_paths, settings.process_modifiers, placement_transform, section_z
                )
                queue_material_paths(
                    "perimeter",
                    f"TYPE:local-perimeter walls={modifier.wall_count}",
                    local_paths,
                )
                for speed_paths, speed_modifier in local_speed_paths:
                    queue_material_paths(
                        "perimeter",
                        f"TYPE:local-perimeter walls={modifier.wall_count} "
                        f"speed={speed_modifier.print_speed_pct:g}%"
                        f"{_local_temperature_label(speed_modifier)}",
                        speed_paths,
                        modifier=speed_modifier,
                    )
            solid_area, sparse_area = _solid_skin_areas(
                infill_area,
                layer_footprints,
                index,
                settings.top_solid_layers,
                settings.bottom_solid_layers,
            )
            solid_fill = _infill_lines(solid_area, line_width, angle)
            layer_solid_skin_paths += len(solid_fill)
            solid_fill, local_solid_fill = _locally_modified_speed_paths(
                solid_fill, settings.process_modifiers, placement_transform, section_z
            )
            queue_material_paths("solid-infill", "TYPE:solid-infill", solid_fill)
            for speed_paths, modifier in local_solid_fill:
                queue_material_paths(
                    "solid-infill",
                    f"TYPE:local-solid-infill speed={modifier.print_speed_pct:g}%"
                    f"{_local_temperature_label(modifier)}",
                    speed_paths,
                    modifier=modifier,
                )
            sparse_area, local_infill = _local_infill_areas(
                sparse_area, settings.process_modifiers, placement_transform, section_z
            )
            if local_infill:
                layer_process_modified = True
            if spacing > 0:
                fill = (
                    _honeycomb_lines(sparse_area, spacing, grid=hex_grid)
                    if settings.infill_pattern == "honeycomb"
                    else _infill_lines(sparse_area, spacing, angle)
                )
                queue_material_paths("infill", "TYPE:infill", fill)
            for local_area, modifier in local_infill:
                local_density = modifier.infill_density_pct
                local_pattern = modifier.infill_pattern or settings.infill_pattern
                local_spacing = line_width / (local_density / 100.0) if local_density > 0 else 0.0
                if local_spacing <= 0:
                    continue
                local_fill = (
                    _honeycomb_lines(local_area, local_spacing)
                    if local_pattern == "honeycomb"
                    else _infill_lines(local_area, local_spacing, angle)
                )
                queue_material_paths(
                    "infill",
                    "TYPE:local-infill "
                    f"density={local_density:g}% speed={modifier.print_speed_pct:g}%"
                    f"{_local_temperature_label(modifier)} "
                    f"pattern={local_pattern}",
                    local_fill,
                    modifier=modifier,
                )
        if isinstance(support_pts, TreeSupports):
            outlines, roof = _tree_support_paths(
                support_pts, section_z, polygons, printer, line_width
            )
        else:
            outlines, roof = _support_paths(
                support_pts, section_z, polygons, printer, line_width, bed_z
            )
        outlines, local_support = _locally_modified_speed_paths(
            outlines, settings.process_modifiers, placement_transform, section_z
        )
        roof, local_support_roof = _locally_modified_speed_paths(
            roof, settings.process_modifiers, placement_transform, section_z
        )
        support_line_width = (
            line_width if isinstance(support_pts, TreeSupports) else SUPPORT_WIDTH_MM
        )
        queue_material_paths("support", "TYPE:support", outlines, path_width_mm=support_line_width)
        for speed_paths, modifier in local_support:
            queue_material_paths(
                "support",
                f"TYPE:local-support speed={modifier.print_speed_pct:g}%"
                f"{_local_temperature_label(modifier)}",
                speed_paths,
                path_width_mm=support_line_width,
                modifier=modifier,
            )
        queue_material_paths("support-interface", "TYPE:support-interface", roof)
        for speed_paths, modifier in local_support_roof:
            queue_material_paths(
                "support-interface",
                f"TYPE:local-support-interface speed={modifier.print_speed_pct:g}%"
                f"{_local_temperature_label(modifier)}",
                speed_paths,
                modifier=modifier,
            )

        layer_tool_order = _ordered_material_tools(
            purge_plan_candidate.layer_tools[index],
            layer_material_counts,
            settings.base_tool,
            preferred_material_tools,
        )
        return (
            tuple(layer_material_batches),
            layer_material_counts,
            layer_tool_order,
            layer_solid_skin_paths,
            layer_process_modified,
            (
                _blocked_purge_path_mask(purge_tower_candidates, layer_material_batches)
                if requires_material_preflight and settings.purge_tower_enabled
                else 0
            ),
        )

    requires_material_preflight = _requires_material_preflight(
        preferred_material_tools,
        settings.base_tool,
    )
    purge_plan = purge_plan_candidate
    purge_tower_layers: tuple[PurgeTowerLayerSegments, ...] = ()
    if requires_material_preflight:
        for index in range(len(layers)):
            (
                layer_material_batches,
                layer_material_counts,
                layer_tool_order,
                layer_solid_skin_paths,
                layer_process_modified,
                blocked_candidate_mask,
            ) = build_layer_material_paths(index)
            layer_material_plans.append(
                LayerMaterialPlan(
                    counts=layer_material_counts,
                    tool_order=layer_tool_order,
                    blocked_candidate_mask=blocked_candidate_mask,
                )
            )
            solid_skin_paths += layer_solid_skin_paths
            if layer_process_modified:
                process_modified_layers.add(index)
            del layer_material_batches

        purge_plan = _bind_purge_plan_to_paths(
            purge_plan_candidate,
            [plan.counts for plan in layer_material_plans],
            settings.base_tool,
            preferred_material_tools,
        )
        if purge_plan.change_count and settings.purge_tower_enabled:
            if effective_adhesion == "raft":
                raise ValueError(
                    "purge tower with raft adhesion is not supported yet; "
                    "disable the purge tower or use another adhesion mode"
                )
            blocked_candidate_mask = _adhesion_blocked_purge_mask(
                purge_tower_candidates,
                adhesion_plan,
                line_width,
            )
            for footprint in layer_footprints:
                blocked_candidate_mask |= _blocked_purge_candidate_mask(
                    purge_tower_candidates,
                    footprint,
                    PURGE_TOWER_CLEARANCE_MM,
                )
            for plan in layer_material_plans:
                blocked_candidate_mask |= plan.blocked_candidate_mask
            tower = _reserve_purge_tower(purge_tower_candidates, blocked_candidate_mask)
            last_changed_layer = max(
                index for index, tools in enumerate(purge_plan.layer_tools) if len(tools) > 1
            )
            tower_layers: list[PurgeTowerLayerSegments] = []
            for layer_index in range(last_changed_layer + 1):
                layer = layers[layer_index]
                tools = purge_plan.layer_tools[layer_index]
                centerline = _purge_tower_centerline(tower, line_width, layer_index)
                tower_layers.append(
                    _purge_tower_segments(
                        centerline,
                        layer.height_mm,
                        line_width,
                        [settings.purge_volume_mm3] * max(0, len(tools) - 1),
                    )
                )
            purge_plan = PurgePlan(
                purge_plan.layer_tools,
                tower,
            )
            purge_tower_layers = tuple(tower_layers)

    thermal_plan = _thermal_plan(settings, purge_plan)
    tool_switching_active = purge_plan.change_count > 0

    # Material candidates complete exact path and purge preflight before writer creation.
    # Plain single-material slices retain the original one-pass build-and-emit fast path.
    writer = _Writer(
        printer,
        retraction_mm=tuning.retraction_mm,
        retraction_speed_mm_s=35.0,
        active_tool=settings.base_tool,
        # the printer's measured flow (coupon) times what print reports taught this material
        flow=printer.flow_pct / 100.0 * tuning.flow_pct / 100.0,
    )
    if tool_switching_active:
        printer_flow = printer.flow_pct / 100.0
        writer.activate_tools(
            {
                tool: (
                    printer_flow * tuning.flow_pct / 100.0
                    if tool == settings.base_tool
                    else printer_flow
                )
                for tool in thermal_plan.used_tools
            }
        )
    writer.lines.extend(
        _header(
            printer,
            settings,
            layers,
            total_layers,
            thermal_plan,
            tool_switching_active=tool_switching_active,
        )
    )
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
    if learned:
        writer.comment(
            "tuning (learned from print reports): "
            + ", ".join(f"{name}={value:g}" for name, value in learned.items())
        )
    writer.comment(
        f"adhesion: mode={effective_adhesion}{adhesion_detail}"
        f" speed={settings.adhesion_speed_pct:g}%"
    )
    base_feed = writer.print_feed
    first_layer_feed = base_feed * (tuning.first_layer_speed_pct / 100)
    adhesion_feed = first_layer_feed * (settings.adhesion_speed_pct / 100)
    if adhesion_plan.skirt:
        writer.print_feed = adhesion_feed
        writer.set_z(layers[0].machine_z, layers[0].height_mm)
        writer.comment("TYPE:skirt")
        writer.loop(adhesion_plan.skirt, line_width)
        writer.print_feed = base_feed

    def here() -> tuple[float, float]:
        if writer.x is None or writer.y is None:
            return seam_anchor
        return writer.x, writer.y

    model_z_offset = 0.0
    if effective_adhesion == "raft":
        raft_paths: list[tuple[str, list[Path2], float]] = []
        for raft_index in range(settings.raft_base_layers):
            base_paths, _ = _raft_paths(
                layer_polygons[0],
                printer,
                line_width,
                settings.raft_margin_mm,
                settings.raft_base_density_pct,
                settings.raft_interface_density_pct,
                base_angle_deg=90.0 * (raft_index % 2),
            )
            raft_paths.append(("raft-base", base_paths, raft_base_layer_height_mm))
        for interface_index in range(settings.raft_interface_layers):
            _, interface_paths = _raft_paths(
                layer_polygons[0],
                printer,
                line_width,
                settings.raft_margin_mm,
                settings.raft_base_density_pct,
                settings.raft_interface_density_pct,
                interface_angle_deg=90.0 * ((interface_index + 1) % 2),
            )
            raft_paths.append(("raft-interface", interface_paths, raft_interface_layer_height_mm))
        machine_z = 0.0
        for raft_index, (kind, paths, layer_height_mm) in enumerate(raft_paths):
            raft_speed_pct = (
                settings.raft_base_speed_pct
                if kind == "raft-base"
                else settings.raft_interface_speed_pct
            )
            writer.print_feed = adhesion_feed * (raft_speed_pct / 100)
            machine_z += layer_height_mm
            writer.comment(
                f"layer {raft_index + 1}/{total_layers} z={machine_z:g} height={layer_height_mm:g}"
            )
            writer.set_z(machine_z, layer_height_mm)
            writer.comment(f"TYPE:{kind}")
            for path in _nearest_first(paths, here()):
                writer.loop(path, line_width)
        model_z_offset = raft_total_height_mm + settings.raft_air_gap_mm
        writer.print_feed = base_feed

    for index, layer in enumerate(layers):
        (
            layer_material_batches,
            regenerated_counts,
            regenerated_tool_order,
            layer_solid_skin_paths,
            layer_process_modified,
            regenerated_blocked_candidate_mask,
        ) = build_layer_material_paths(index)
        if requires_material_preflight:
            plan = layer_material_plans[index]
            if (
                regenerated_counts != plan.counts
                or regenerated_tool_order != plan.tool_order
                or (
                    settings.purge_tower_enabled
                    and regenerated_blocked_candidate_mask != plan.blocked_candidate_mask
                )
            ):
                raise RuntimeError("material path regeneration diverged from preflight")
        else:
            plan = LayerMaterialPlan(
                counts=regenerated_counts,
                tool_order=regenerated_tool_order,
            )
            solid_skin_paths += layer_solid_skin_paths
            if layer_process_modified:
                process_modified_layers.add(index)
        machine_z = layer.machine_z + model_z_offset
        writer.comment(
            f"layer {index + 1 + raft_layer_count}/{total_layers} "
            f"z={machine_z:g} height={layer.height_mm:g}"
        )
        writer.set_z(machine_z, layer.height_mm)
        writer.print_feed = first_layer_feed if index == 0 else base_feed
        if index == 0:
            writer.print_feed = adhesion_feed
            if adhesion_plan.brim:
                writer.comment("TYPE:brim")
            for loop in adhesion_plan.brim:
                writer.loop(loop, line_width)
                brim_loops += 1
            if adhesion_plan.mouse_ears:
                writer.comment("TYPE:mouse-ear")
            for path in _nearest_first([list(path) for path in adhesion_plan.mouse_ears], here()):
                writer.loop(path, line_width)
            writer.print_feed = first_layer_feed

        emitted_tools: set[int] = set()
        base_layer_tool = plan.tool_order[0]
        emitted_tools.add(base_layer_tool)
        _emit_material_tool_batches(
            writer,
            layer_material_batches,
            plan,
            base_layer_tool,
            index,
            thermal_plan,
            here,
        )

        tower_segments = purge_tower_layers[index] if index < len(purge_tower_layers) else None
        if tower_segments is not None and not tower_segments.structural.is_empty:
            writer.comment("TYPE:purge-tower-structure")
            writer.loop(
                [(float(point[0]), float(point[1])) for point in tower_segments.structural.coords],
                line_width,
            )

        for transition_index, tool in enumerate(plan.tool_order[1:]):
            if tool != writer.active_tool:
                writer.select_tool(tool)
                writer.lines.append(f"M109 S{thermal_plan.nozzle_c_for(tool):g}")
                if tower_segments is not None:
                    purge_segment = tower_segments.purge[transition_index]
                    writer.comment(
                        "TYPE:purge-tower "
                        f"transition={transition_index + 1}/{len(tower_segments.purge)} "
                        f"tool=T{tool} volume={settings.purge_volume_mm3:g}mm3"
                    )
                    writer.purge(
                        [(float(point[0]), float(point[1])) for point in purge_segment.coords],
                        settings.purge_volume_mm3,
                    )
                else:
                    # A tower-disabled final return has no following model path to restore
                    # the base tool. Keep its retract state balanced without counting the
                    # prime as deposited filament or purge volume.
                    writer._prime_active_tool()
            if tool not in emitted_tools:
                emitted_tools.add(tool)
                _emit_material_tool_batches(
                    writer,
                    layer_material_batches,
                    plan,
                    tool,
                    index,
                    thermal_plan,
                    here,
                )
        del layer_material_batches
        if tool_switching_active and writer.active_tool != settings.base_tool:
            raise RuntimeError("material layer did not return to the base tool")

    if purge_plan.change_count:
        if purge_plan.tower is not None:
            tower_min_x, tower_min_y, _, _ = purge_plan.tower.bounds
            writer.comment(
                "purge-plan: "
                f"layers={purge_plan.changed_layer_count} changes={purge_plan.change_count} "
                f"tower=reserved x={tower_min_x:g} y={tower_min_y:g} "
                f"width={settings.purge_tower_width_mm:g}mm paths=enabled"
            )
        else:
            writer.comment(
                "purge-plan: "
                f"layers={purge_plan.changed_layer_count} changes={purge_plan.change_count} "
                "tower=disabled paths=disabled"
            )

    writer.lines.extend(_footer(thermal_plan if tool_switching_active else None))
    gcode_text = "\n".join(writer.lines) + "\n"

    material_g = writer.filament_mm / 1000.0 * math.pi * (FILAMENT_DIAMETER_MM / 2) ** 2 * 1.24
    stats = SliceStats(
        total_layers=total_layers,
        layer_height_mode="adaptive" if settings.adaptive_layer_height else "fixed",
        min_layer_height_mm=round(
            min(
                [layer.height_mm for layer in layers]
                + (
                    [raft_base_layer_height_mm, raft_interface_layer_height_mm]
                    if raft_enabled
                    else []
                )
            ),
            3,
        ),
        max_layer_height_mm=round(
            max(
                [layer.height_mm for layer in layers]
                + (
                    [raft_base_layer_height_mm, raft_interface_layer_height_mm]
                    if raft_enabled
                    else []
                )
            ),
            3,
        ),
        filament_used_mm=round(writer.filament_mm, 1),
        filament_used_by_tool_mm={
            f"T{tool}": round(filament_mm, 3)
            for tool, filament_mm in sorted(writer.filament_mm_by_tool.items())
        },
        filament_used_g=round(material_g, 2),
        estimated_time_s=round(
            (sum(layer.height_mm for layer in layers) + raft_total_height_mm) * 8
            + writer.filament_mm / 5
            + writer.travel_time_s
            + writer.retraction_time_s,
            1,
        ),
        support_columns=(
            len(support_pts.contacts)
            if isinstance(support_pts, TreeSupports)
            else len(support_pts.columns)
        ),
        support_type=settings.support_type,
        support_generation_mode=settings.support_generation_mode,
        support_branches=(
            len(support_pts.branches) if isinstance(support_pts, TreeSupports) else 0
        ),
        support_trunks=(support_pts.trunks if isinstance(support_pts, TreeSupports) else 0),
        support_modifiers=len(settings.support_modifiers),
        support_blocked_faces=blocked_support_faces,
        support_enforced_faces=enforced_support_faces,
        process_modifiers=len(settings.process_modifiers),
        process_modified_layers=len(process_modified_layers),
        material_assigned_regions=sum(
            modifier.material_slot is not None for modifier in settings.process_modifiers
        ),
        planned_tool_change_layers=purge_plan.changed_layer_count,
        planned_tool_changes=purge_plan.change_count,
        planned_purge_volume_mm3=purge_plan.change_count * settings.purge_volume_mm3,
        purge_tower_reserved=purge_plan.tower is not None,
        purge_tower_x_mm=(
            round(purge_plan.tower.bounds[0], 3) if purge_plan.tower is not None else 0.0
        ),
        purge_tower_y_mm=(
            round(purge_plan.tower.bounds[1], 3) if purge_plan.tower is not None else 0.0
        ),
        purge_tower_width_mm=(
            settings.purge_tower_width_mm if purge_plan.tower is not None else 0.0
        ),
        travel_mm=round(writer.travel_mm, 1),
        xy_compensation_mm=printer.xy_compensation_mm,
        shrinkage_pct=printer.shrinkage_pct,
        flow_pct=printer.flow_pct,
        tuning=learned,
        adhesion_mode=effective_adhesion,
        brim_width_mm=effective_brim_mm,
        brim_loops=brim_loops,
        mouse_ear_diameter_mm=(
            settings.mouse_ear_diameter_mm if effective_adhesion == "mouse_ears" else 0.0
        ),
        mouse_ear_count=mouse_ear_count,
        mouse_ear_requested_count=len(settings.mouse_ear_points_mm),
        mouse_ear_rejected_count=(
            len(settings.mouse_ear_points_mm) - mouse_ear_count
            if effective_adhesion == "mouse_ears"
            else 0
        ),
        adhesion_speed_pct=(settings.adhesion_speed_pct if effective_adhesion != "none" else 100.0),
        raft_layers=raft_layer_count,
        raft_base_layers=(settings.raft_base_layers if raft_enabled else 0),
        raft_interface_layers=(settings.raft_interface_layers if raft_enabled else 0),
        raft_base_layer_height_mm=(raft_base_layer_height_mm if raft_enabled else 0.0),
        raft_interface_layer_height_mm=(raft_interface_layer_height_mm if raft_enabled else 0.0),
        raft_base_speed_pct=(settings.raft_base_speed_pct if raft_enabled else 0.0),
        raft_interface_speed_pct=(settings.raft_interface_speed_pct if raft_enabled else 0.0),
        raft_margin_mm=(settings.raft_margin_mm if raft_enabled else 0.0),
        raft_air_gap_mm=(settings.raft_air_gap_mm if raft_enabled else 0.0),
        raft_base_density_pct=(settings.raft_base_density_pct if raft_enabled else 0.0),
        raft_interface_density_pct=(settings.raft_interface_density_pct if raft_enabled else 0.0),
        raft_density_profiled=(settings.raft_density_profiled if raft_enabled else False),
        solid_skin_paths=solid_skin_paths,
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
