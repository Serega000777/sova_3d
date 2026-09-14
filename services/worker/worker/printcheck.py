"""Print analysis (E7): F-008 checks, F-013 mass/time/cost, F-030 Printability Score,
F-031 orientation optimization.

Everything here is a v1 heuristic, labelled as such in the report: no slicer
dry-run yet. All lengths are millimetres, masses grams, money in the material
profile's currency. `PrintAnalysis` is the contract (schema_version 1); the
score is explainable — every sub-score carries its weight and the reason.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from worker.repair import Diagnostics, diagnose

SCHEMA_VERSION: Literal[1] = 1
Severity = Literal["info", "warning", "error"]
Status = Literal["green", "yellow", "red"]


# --- inputs ---------------------------------------------------------------------------------


class PrinterProfile(BaseModel):
    """What the analysis needs to know about the machine (T-058/T-071)."""

    name: str = "Generic 256 mm FDM"
    bed_x_mm: float = 256.0
    bed_y_mm: float = 256.0
    bed_z_mm: float = 256.0
    nozzle_mm: float = 0.4
    layer_height_mm: float = 0.2
    max_overhang_deg: float = 45.0
    print_speed_mm_s: float = 60.0
    technology: Literal["fdm", "resin"] = "fdm"


class MaterialProfile(BaseModel):
    """Density/price/shrinkage (T-061/T-062/T-072)."""

    name: str = "PLA"
    density_g_cm3: float = 1.24
    price_per_kg: float = 25.0
    currency: str = "USD"
    shrinkage_pct: float = 0.3
    min_wall_mm: float | None = None  # defaults to 2 x nozzle


# --- outputs --------------------------------------------------------------------------------


class PrintWarning(BaseModel):
    code: str
    severity: Severity
    message: str
    details: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class Metrics(BaseModel):
    bbox_mm: tuple[float, float, float]
    volume_mm3: float | None
    surface_area_mm2: float
    mass_g: float | None
    support_volume_mm3: float
    support_mass_g: float | None
    layers: int
    print_time_min: float | None
    material_cost: float | None
    support_cost: float | None
    total_cost: float | None
    currency: str
    min_wall_mm: float | None
    thin_area_fraction: float
    overhang_area_fraction: float
    contact_area_mm2: float
    contact_ratio: float


class SubScore(BaseModel):
    name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    reason: str


class Score(BaseModel):
    total: float = Field(ge=0, le=100)
    status: Status
    subscores: list[SubScore]


class Orientation(BaseModel):
    """Rotation applied before analysis, as axis-angle steps (deg) about X then Y."""

    rot_x_deg: float = 0.0
    rot_y_deg: float = 0.0
    label: str = "as modelled"


class OrientationCandidate(BaseModel):
    orientation: Orientation
    score: float
    support_volume_mm3: float
    print_time_min: float | None
    height_mm: float
    contact_ratio: float
    overhang_area_fraction: float


class PrintAnalysis(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    heuristics_version: str = "v1"
    printer: PrinterProfile
    material: MaterialProfile
    orientation: Orientation
    fits_bed: bool
    watertight: bool
    metrics: Metrics
    warnings: list[PrintWarning] = Field(default_factory=list)
    score: Score
    summary: str
    candidates: list[OrientationCandidate] = Field(default_factory=list)
    recommended: OrientationCandidate | None = None

    @property
    def errors(self) -> list[PrintWarning]:
        return [w for w in self.warnings if w.severity == "error"]


# --- helpers --------------------------------------------------------------------------------

DEFAULT_PRINTER = PrinterProfile()
DEFAULT_MATERIAL = MaterialProfile()
CONTACT_EPS_MM = 0.05
SAMPLE_FACES = 2000


def _rotated(mesh: trimesh.Trimesh, orientation: Orientation) -> trimesh.Trimesh:
    out = mesh.copy()
    if orientation.rot_x_deg:
        out.apply_transform(
            trimesh.transformations.rotation_matrix(math.radians(orientation.rot_x_deg), [1, 0, 0])
        )
    if orientation.rot_y_deg:
        out.apply_transform(
            trimesh.transformations.rotation_matrix(math.radians(orientation.rot_y_deg), [0, 1, 0])
        )
    # Rest on the bed with the bbox corner at the origin.
    out.apply_translation(-out.bounds[0])
    return out


def _bed_fit(extents: np.ndarray, printer: PrinterProfile) -> tuple[bool, dict[str, float]]:
    """T-058: fits as-is or with a 90° yaw; height must fit either way."""
    x, y, z = (float(v) for v in extents)
    fits_xy = (x <= printer.bed_x_mm and y <= printer.bed_y_mm) or (
        y <= printer.bed_x_mm and x <= printer.bed_y_mm
    )
    fits = fits_xy and z <= printer.bed_z_mm
    margins = {
        "x_margin_mm": round(printer.bed_x_mm - x, 3),
        "y_margin_mm": round(printer.bed_y_mm - y, 3),
        "z_margin_mm": round(printer.bed_z_mm - z, 3),
    }
    return fits, margins


def _overhangs(mesh: trimesh.Trimesh, printer: PrinterProfile) -> tuple[float, float, float]:
    """T-060: returns (overhang_area_fraction, support_volume_proxy, contact_area).

    A face is unsupported when its outward normal points down more than the printer's
    max overhang angle from vertical and it is not lying on the bed. The support proxy is
    the column under each unsupported face (area x height above bed), which is what a
    slicer would fill with support in the worst case."""
    normals = np.asarray(mesh.face_normals)
    areas = np.asarray(mesh.area_faces)
    centroids = np.asarray(mesh.triangles_center)
    bed_z = float(mesh.bounds[0][2])
    down = -normals[:, 2]  # 1 = straight down
    threshold = math.cos(math.radians(printer.max_overhang_deg))
    on_bed = centroids[:, 2] - bed_z <= CONTACT_EPS_MM
    contact = float(areas[on_bed & (down > 0.99)].sum())
    unsupported = (down > threshold) & ~on_bed
    overhang_area = float(areas[unsupported].sum())
    # Column projected onto the bed: horizontal area x height.
    horizontal = areas[unsupported] * down[unsupported]
    support_volume = float((horizontal * (centroids[unsupported, 2] - bed_z)).sum())
    total = float(areas.sum()) or 1.0
    return overhang_area / total, support_volume, contact


def _thin_walls(mesh: trimesh.Trimesh, min_wall_mm: float) -> tuple[float | None, float]:
    """T-059: ray-cast thickness at sampled face centroids; fraction of area under the limit."""
    if len(mesh.faces) == 0:
        return None, 0.0
    rng = np.random.default_rng(0)  # deterministic sampling for golden fixtures
    count = min(SAMPLE_FACES, len(mesh.faces))
    areas = np.asarray(mesh.area_faces)
    probs = areas / areas.sum() if areas.sum() > 0 else None
    picks = rng.choice(len(mesh.faces), size=count, replace=len(mesh.faces) < count, p=probs)
    points = np.asarray(mesh.triangles_center)[picks]
    normals = np.asarray(mesh.face_normals)[picks]
    try:
        thickness = trimesh.proximity.thickness(
            mesh, points, exterior=False, normals=normals, method="ray"
        )
    except Exception:
        return None, 0.0
    thickness = np.asarray(thickness, dtype=float)
    finite = thickness[np.isfinite(thickness) & (thickness > 0)]
    if finite.size == 0:
        return None, 0.0
    thin = float(np.count_nonzero(finite < min_wall_mm)) / float(finite.size)
    return float(np.percentile(finite, 5)), thin


def _time_estimate(
    volume_mm3: float | None, support_mm3: float, height_mm: float, printer: PrinterProfile
) -> tuple[int, float | None]:
    layers = max(int(math.ceil(height_mm / printer.layer_height_mm)), 1)
    if volume_mm3 is None:
        return layers, None
    flow = printer.layer_height_mm * printer.nozzle_mm * printer.print_speed_mm_s  # mm^3/s
    seconds = (volume_mm3 + support_mm3) / flow + layers * 2.0  # per-layer overhead
    return layers, round(seconds / 60.0, 1)


def _mass(volume_mm3: float | None, material: MaterialProfile) -> float | None:
    if volume_mm3 is None:
        return None
    return round(volume_mm3 / 1000.0 * material.density_g_cm3, 3)  # mm^3 -> cm^3 -> g


def _cost(mass_g: float | None, material: MaterialProfile) -> float | None:
    if mass_g is None:
        return None
    return round(mass_g / 1000.0 * material.price_per_kg, 4)


# --- analysis -------------------------------------------------------------------------------


def analyze(
    mesh: trimesh.Trimesh,
    *,
    printer: PrinterProfile = DEFAULT_PRINTER,
    material: MaterialProfile = DEFAULT_MATERIAL,
    orientation: Orientation | None = None,
    diagnostics: Diagnostics | None = None,
    thin_walls: tuple[float | None, float] | None = None,
) -> PrintAnalysis:
    orientation = orientation or Orientation()
    placed = _rotated(mesh, orientation)
    diag = diagnostics or diagnose(placed)
    warnings: list[PrintWarning] = []

    watertight = diag.watertight and diag.winding_consistent
    volume = diag.volume_mm3 if watertight else None
    if not watertight:
        warnings.append(
            PrintWarning(
                code="not_manifold",
                severity="error",
                message="The model is not a closed solid; slicers may print it wrong.",
                details={"holes": diag.holes, "non_manifold_edges": diag.non_manifold_edges},
            )
        )
    if diag.degenerate_faces:
        warnings.append(
            PrintWarning(
                code="degenerate_faces",
                severity="warning",
                message="Zero-area triangles found; run Repair.",
                details={"count": diag.degenerate_faces},
            )
        )

    extents = np.asarray(placed.extents, dtype=float)
    fits, margins = _bed_fit(extents, printer)
    if not fits:
        warnings.append(
            PrintWarning(
                code="exceeds_bed",
                severity="error",
                message=f"The model does not fit the {printer.name} build volume.",
                details={**margins, "bbox": "x".join(f"{v:.1f}" for v in extents)},
            )
        )

    min_wall = material.min_wall_mm or 2.0 * printer.nozzle_mm
    wall_p5, thin_fraction = thin_walls or _thin_walls(placed, min_wall)
    if thin_fraction > 0.02:
        warnings.append(
            PrintWarning(
                code="thin_walls",
                severity="error" if thin_fraction > 0.2 else "warning",
                message=f"Some walls are thinner than {min_wall:g} mm.",
                details={"area_fraction": round(thin_fraction, 4), "limit_mm": min_wall},
            )
        )

    overhang_fraction, support_volume, contact_area = _overhangs(placed, printer)
    footprint = float(extents[0] * extents[1]) or 1.0
    contact_ratio = min(contact_area / footprint, 1.0)
    if overhang_fraction > 0.05:
        warnings.append(
            PrintWarning(
                code="overhangs",
                severity="warning" if overhang_fraction < 0.3 else "error",
                message=f"Overhangs steeper than {printer.max_overhang_deg:g}° need support.",
                details={"area_fraction": round(overhang_fraction, 4)},
            )
        )
    if contact_ratio < 0.15:
        warnings.append(
            PrintWarning(
                code="small_footprint",
                severity="warning",
                message="Very little contact with the bed; adhesion may fail.",
                details={"contact_ratio": round(contact_ratio, 4)},
            )
        )

    layers, print_time = _time_estimate(volume, support_volume, float(extents[2]), printer)
    mass = _mass(volume, material)
    support_mass = _mass(support_volume, material)
    material_cost = _cost(mass, material)
    support_cost = _cost(support_mass, material)
    total_cost = None if material_cost is None else round(material_cost + (support_cost or 0.0), 4)

    metrics = Metrics(
        bbox_mm=(
            round(float(extents[0]), 3),
            round(float(extents[1]), 3),
            round(float(extents[2]), 3),
        ),
        volume_mm3=volume,
        surface_area_mm2=float(placed.area),
        mass_g=mass,
        support_volume_mm3=round(support_volume, 3),
        support_mass_g=support_mass,
        layers=layers,
        print_time_min=print_time,
        material_cost=material_cost,
        support_cost=support_cost,
        total_cost=total_cost,
        currency=material.currency,
        min_wall_mm=None if wall_p5 is None else round(wall_p5, 3),
        thin_area_fraction=round(thin_fraction, 4),
        overhang_area_fraction=round(overhang_fraction, 4),
        contact_area_mm2=round(contact_area, 3),
        contact_ratio=round(contact_ratio, 4),
    )
    has_errors = any(w.severity == "error" for w in warnings)
    score = _score(
        watertight, fits, thin_fraction, overhang_fraction, contact_ratio, diag, has_errors
    )
    summary = _summary(score, warnings, printer, material, metrics)
    return PrintAnalysis(
        printer=printer,
        material=material,
        orientation=orientation,
        fits_bed=fits,
        watertight=watertight,
        metrics=metrics,
        warnings=warnings,
        score=score,
        summary=summary,
    )


def _score(
    watertight: bool,
    fits: bool,
    thin_fraction: float,
    overhang_fraction: float,
    contact_ratio: float,
    diag: Diagnostics,
    has_errors: bool,
) -> Score:
    """T-063: weighted, explainable. Any error-level finding caps the total (red)."""
    geometry = 100.0 if watertight else 0.0
    if watertight and diag.degenerate_faces:
        geometry = 80.0
    walls = max(0.0, 100.0 - thin_fraction * 400.0)  # 25% thin area -> 0
    overhang = max(0.0, 100.0 - overhang_fraction * 250.0)  # 40% overhang area -> 0
    fit = 100.0 if fits else 0.0
    stability = min(100.0, 40.0 + contact_ratio * 120.0)  # 50% footprint contact -> 100
    subscores = [
        SubScore(
            name="geometry",
            score=geometry,
            weight=0.30,
            reason=(
                "closed, consistently oriented solid"
                if watertight
                else "open edges or flipped faces"
            ),
        ),
        SubScore(
            name="walls",
            score=round(walls, 1),
            weight=0.20,
            reason=(f"{thin_fraction:.0%} of the surface is thinner than the minimum wall"),
        ),
        SubScore(
            name="overhangs",
            score=round(overhang, 1),
            weight=0.20,
            reason=(f"{overhang_fraction:.0%} of the surface needs support"),
        ),
        SubScore(
            name="bed_fit",
            score=fit,
            weight=0.20,
            reason=("fits the build volume" if fits else "exceeds the build volume"),
        ),
        SubScore(
            name="stability",
            score=round(stability, 1),
            weight=0.10,
            reason=(f"{contact_ratio:.0%} of the footprint touches the bed"),
        ),
    ]
    total = round(sum(s.score * s.weight for s in subscores), 1)
    if has_errors:
        status: Status = "red"
        total = min(total, 49.0)
    elif total >= 80 and thin_fraction <= 0.02:
        status = "green"
    else:
        status = "yellow"
    return Score(total=total, status=status, subscores=subscores)


def _summary(
    score: Score,
    warnings: list[PrintWarning],
    printer: PrinterProfile,
    material: MaterialProfile,
    metrics: Metrics,
) -> str:
    head = f"Printability {score.total:.0f}/100 ({score.status})."
    parts = [head]
    if metrics.mass_g is not None and metrics.print_time_min is not None:
        parts.append(
            f"About {metrics.mass_g:.0f} g of {material.name}, "
            f"~{metrics.print_time_min:.0f} min on {printer.name}"
            + (
                f", {metrics.total_cost:.2f} {metrics.currency}."
                if metrics.total_cost is not None
                else "."
            )
        )
    for warning in warnings:
        if warning.severity != "info":
            parts.append(warning.message)
    return " ".join(parts)


# --- orientation optimization (T-065..T-067) ------------------------------------------------

CANDIDATE_ORIENTATIONS: tuple[Orientation, ...] = tuple(
    Orientation(rot_x_deg=rx, rot_y_deg=ry, label=label)
    for rx, ry, label in (
        (0, 0, "as modelled"),
        (180, 0, "upside down"),
        (90, 0, "front face down"),
        (-90, 0, "back face down"),
        (0, 90, "left side down"),
        (0, -90, "right side down"),
        (45, 0, "tilted 45° about X"),
        (-45, 0, "tilted -45° about X"),
        (0, 45, "tilted 45° about Y"),
        (0, -45, "tilted -45° about Y"),
    )
)


def candidates(
    mesh: trimesh.Trimesh,
    *,
    printer: PrinterProfile = DEFAULT_PRINTER,
    material: MaterialProfile = DEFAULT_MATERIAL,
) -> list[OrientationCandidate]:
    """T-065/T-066: score each candidate on support, time, stability and overhangs."""
    out: list[OrientationCandidate] = []
    diag = diagnose(mesh)
    min_wall = material.min_wall_mm or 2.0 * printer.nozzle_mm
    thin = _thin_walls(mesh, min_wall)
    for orientation in CANDIDATE_ORIENTATIONS:
        analysis = analyze(
            mesh,
            printer=printer,
            material=material,
            orientation=orientation,
            diagnostics=diag,
            thin_walls=thin,
        )
        out.append(
            OrientationCandidate(
                orientation=orientation,
                score=analysis.score.total,
                support_volume_mm3=analysis.metrics.support_volume_mm3,
                print_time_min=analysis.metrics.print_time_min,
                height_mm=analysis.metrics.bbox_mm[2],
                contact_ratio=analysis.metrics.contact_ratio,
                overhang_area_fraction=analysis.metrics.overhang_area_fraction,
            )
        )
    return out


def best_candidate(cands: list[OrientationCandidate]) -> OrientationCandidate:
    """Highest score; ties broken by less support, then shorter print, then more contact."""
    return sorted(
        cands,
        key=lambda c: (
            -c.score,
            c.support_volume_mm3,
            c.print_time_min if c.print_time_min is not None else math.inf,
            -c.contact_ratio,
        ),
    )[0]


def optimize(
    mesh: trimesh.Trimesh,
    *,
    printer: PrinterProfile = DEFAULT_PRINTER,
    material: MaterialProfile = DEFAULT_MATERIAL,
) -> PrintAnalysis:
    """T-067: non-destructive recommendation — the analysis of the best orientation, with the
    full candidate list attached. Applying it is the caller's decision."""
    cands = candidates(mesh, printer=printer, material=material)
    best = best_candidate(cands)
    analysis = analyze(
        mesh,
        printer=printer,
        material=material,
        orientation=best.orientation,
        diagnostics=diagnose(mesh),
    )
    analysis.candidates = cands
    analysis.recommended = best
    return analysis


def apply_orientation(mesh: trimesh.Trimesh, orientation: Orientation) -> trimesh.Trimesh:
    return _rotated(mesh, orientation)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    if "--emit-schema" in sys.argv:
        contracts = Path(__file__).resolve().parents[3] / "packages" / "contracts"
        target = contracts / "print-analysis.schema.json"
        payload = json.dumps(PrintAnalysis.model_json_schema(), indent=2) + "\n"
        target.write_text(payload, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
