"""Engineering facts from a mesh (T-117, F-005).

What an engineer would measure before answering "is this wall too thin?": the wall
thickness distribution of the whole part and of the area the user pointed at, how slender
the part is, and what it weighs in each material. Deterministic (fixed sampling seed),
sandboxed like every other operation on a mesh, and honest about being a sampled estimate.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from worker.importers.common import as_single_mesh, to_platform_axes
from worker.paint import Region, inside_region

SAMPLE_FACES = 4000


class WallStats(BaseModel):
    """Thickness measured by ray-casting through the part at sampled faces (mm)."""

    samples: int
    min_mm: float
    p5_mm: float
    median_mm: float
    max_mm: float
    # Share of the sampled area thinner than `limit_mm` (the limit the caller asked about).
    limit_mm: float
    thin_fraction: float


class EngineeringFacts(BaseModel):
    ok: bool
    message: str | None = None
    bbox_mm: list[float] = Field(default_factory=list)
    volume_mm3: float | None = None
    area_mm2: float | None = None
    watertight: bool = False
    faces: int = 0
    walls: WallStats | None = None
    # The same measurement restricted to the faces inside the region the user drew.
    region_walls: WallStats | None = None
    region_faces: int = 0
    # Longest extent over the typical wall: a lever for whatever load the part sees.
    slenderness: float | None = None
    # grams per material id, from the densities the caller passed in
    mass_g: dict[str, float] = Field(default_factory=dict)


class FactsRequest(BaseModel):
    limit_mm: float = 1.6
    region: Region | None = None
    densities_g_cm3: dict[str, float] = Field(default_factory=dict)


def _thickness_at(mesh: trimesh.Trimesh, picks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Thickness under the chosen faces and the area each one stands for (mm, mm²)."""
    points = np.asarray(mesh.triangles_center)[picks]
    normals = np.asarray(mesh.face_normals)[picks]
    try:
        thickness = trimesh.proximity.thickness(
            mesh, points, exterior=False, normals=normals, method="ray"
        )
    except Exception:
        return np.empty(0), np.empty(0)
    values = np.asarray(thickness, dtype=float)
    keep = np.isfinite(values) & (values > 0)
    return values[keep], np.asarray(mesh.area_faces, dtype=float)[picks][keep]


def _weighted_percentile(values: np.ndarray, weights: np.ndarray, fraction: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    index = int(np.searchsorted(cumulative, fraction * cumulative[-1]))
    return float(values[order][min(index, values.size - 1)])


def _stats(values: np.ndarray, weights: np.ndarray, limit_mm: float) -> WallStats | None:
    """Statistics by surface area, so a big thin face weighs more than a sliver."""
    if values.size == 0 or weights.sum() <= 0:
        return None
    return WallStats(
        samples=int(values.size),
        min_mm=round(float(values.min()), 3),
        p5_mm=round(_weighted_percentile(values, weights, 0.05), 3),
        median_mm=round(_weighted_percentile(values, weights, 0.5), 3),
        max_mm=round(float(values.max()), 3),
        limit_mm=limit_mm,
        thin_fraction=round(float(weights[values < limit_mm].sum() / weights.sum()), 4),
    )


def _pick_faces(rng: np.random.Generator, candidates: np.ndarray) -> np.ndarray:
    """Every face when there are few; a plain random subset when there are many."""
    if candidates.size <= SAMPLE_FACES:
        return candidates
    chosen: np.ndarray = rng.choice(candidates, size=SAMPLE_FACES, replace=False)
    return chosen


def measure(mesh: trimesh.Trimesh, request: FactsRequest) -> EngineeringFacts:
    if mesh.is_empty or len(mesh.faces) == 0:
        return EngineeringFacts(ok=False, message="the model has no faces to measure")
    extents = np.asarray(mesh.extents, dtype=float)
    watertight = bool(mesh.is_watertight)
    volume = float(mesh.volume) if watertight else None
    facts = EngineeringFacts(
        ok=True,
        bbox_mm=[round(float(v), 3) for v in extents],
        volume_mm3=None if volume is None else round(abs(volume), 3),
        area_mm2=round(float(mesh.area), 3),
        watertight=watertight,
        faces=int(len(mesh.faces)),
    )

    rng = np.random.default_rng(0)  # the same answer for the same part, every time
    picks = _pick_faces(rng, np.arange(len(mesh.faces)))
    facts.walls = _stats(*_thickness_at(mesh, picks), request.limit_mm)

    if request.region is not None:
        inside = inside_region(np.asarray(mesh.triangles_center), request.region)
        region_faces = np.flatnonzero(inside)
        facts.region_faces = int(region_faces.size)
        if region_faces.size:
            chosen = _pick_faces(rng, region_faces)
            facts.region_walls = _stats(*_thickness_at(mesh, chosen), request.limit_mm)

    if facts.walls is not None and facts.walls.median_mm > 0:
        facts.slenderness = round(float(extents.max()) / facts.walls.median_mm, 2)
    if volume is not None:
        for material_id, density in request.densities_g_cm3.items():
            facts.mass_g[material_id] = round(abs(volume) / 1000.0 * density, 2)
    return facts


def measure_file(source: Path, source_format: str, request: FactsRequest) -> EngineeringFacts:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None:
        return EngineeringFacts(ok=False, message="the file has no mesh to measure")
    mesh = to_platform_axes(mesh.copy(), source_format)
    mesh.merge_vertices()  # STL repeats every corner; volume needs the shell stitched
    return measure(mesh, request)


def run_in_sandbox(
    source: Path, source_format: str, request: FactsRequest, limits: Any | None = None
) -> EngineeringFacts:
    """Measure in the sandboxed child, like every other operation on an uploaded mesh."""
    from worker import sandbox

    outcome = sandbox.run(
        "worker.engineering",
        [source_format, str(source), request.model_dump_json()],
        input_path=source,
        limits=limits or sandbox.DEFAULT_LIMITS,
    )
    if not outcome.ok:
        return EngineeringFacts(ok=False, message=outcome.message)
    return EngineeringFacts.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: engineering <src_fmt> <src> <request-json>
    import sys

    source_format, source_path, payload = sys.argv[1:4]
    try:
        outcome = measure_file(
            Path(source_path), source_format, FactsRequest.model_validate_json(payload)
        )
        print(json.dumps(outcome.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
