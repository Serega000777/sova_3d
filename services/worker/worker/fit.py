"""AI Fit Test and Assembly (T-129/T-178, F-027/F-010).

Part B is placed against part A (centred on it by default, then offset), and the two
surfaces are measured against each other: how deep one runs into the other, how close
they come where they do not, and where. Signed distances on sampled surface points carry
the verdict (they never fail on an imperfect mesh); the exact interference volume is added
when the boolean engine agrees to compute it. Sandboxed, deterministic sampling.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from worker.importers.common import as_single_mesh

SAMPLES = 4000
TOUCH_MM = 0.05  # closer than this is a collision, not a fit

Verdict = Literal["collides", "press", "transition", "sliding", "loose", "apart"]


class Placement(BaseModel):
    """Where part B goes relative to part A, in A's millimetres."""

    align: Literal["centre", "origin"] = "centre"
    offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate_z_deg: float = 0.0


class FitRequest(BaseModel):
    placement: Placement = Field(default_factory=Placement)
    samples: int = Field(default=SAMPLES, ge=200, le=20_000)
    auto_place: bool = False


class AssemblyCandidate(BaseModel):
    label: str
    placement: Placement
    verdict: Verdict
    max_penetration_mm: float
    min_clearance_mm: float | None = None


class Contact(BaseModel):
    bbox_min_mm: list[float]
    bbox_max_mm: list[float]
    points: int


class FitResult(BaseModel):
    ok: bool
    message: str | None = None
    verdict: Verdict | None = None
    # deepest run of one part into the other (mm); 0 when they never overlap
    max_penetration_mm: float = 0.0
    # closest approach of the two surfaces where they do not overlap (mm)
    min_clearance_mm: float | None = None
    # share of B's sampled surface that lies inside A, and of A's inside B
    b_inside_a_fraction: float = 0.0
    a_inside_b_fraction: float = 0.0
    interference_mm3: float | None = None
    contact: Contact | None = None
    a_bbox_mm: list[list[float]] = Field(default_factory=list)
    b_bbox_mm: list[list[float]] = Field(default_factory=list)
    placement: Placement | None = None
    candidates: list[AssemblyCandidate] = Field(default_factory=list)


def place(a: trimesh.Trimesh, b: trimesh.Trimesh, placement: Placement) -> trimesh.Trimesh:
    """B moved into A's space: rotated about its own centre, centred on A, then offset."""
    moved = b.copy()
    if placement.rotate_z_deg:
        centre = moved.bounds.mean(axis=0)
        moved.apply_transform(
            trimesh.transformations.rotation_matrix(
                np.radians(placement.rotate_z_deg), [0, 0, 1], centre
            )
        )
    if placement.align == "centre":
        moved.apply_translation(a.bounds.mean(axis=0) - moved.bounds.mean(axis=0))
    moved.apply_translation(np.asarray(placement.offset_mm, dtype=float))
    return moved


def _inside_depths(host: trimesh.Trimesh, points: np.ndarray) -> np.ndarray:
    """Signed distance to `host` at `points`: positive inside, negative outside."""
    if len(points) == 0:
        return np.empty(0)
    try:
        return np.asarray(trimesh.proximity.signed_distance(host, points), dtype=float)
    except Exception:
        return np.empty(0)


def verdict_for(penetration: float, clearance: float | None) -> Verdict:
    """The gap is measured per side; the fit words follow the knowledge base's diametral
    allowances halved (sliding = +0.3 on a diameter = 0.15 a side)."""
    if penetration > TOUCH_MM:
        return "collides"
    if clearance is None:
        return "apart"
    if clearance < 0.05:
        return "press"
    if clearance < 0.1:
        return "transition"
    if clearance < 0.25:
        return "sliding"
    if clearance < 1.5:
        return "loose"
    return "apart"


def check_fit(
    a: trimesh.Trimesh,
    b: trimesh.Trimesh,
    request: FitRequest,
    *,
    exact_interference: bool = True,
) -> FitResult:
    if a.is_empty or b.is_empty or len(a.faces) == 0 or len(b.faces) == 0:
        return FitResult(ok=False, message="both parts need faces to be fitted")
    placed = place(a, b, request.placement)
    rng_seed = 0
    b_points, _ = trimesh.sample.sample_surface(placed, request.samples, seed=rng_seed)
    a_points, _ = trimesh.sample.sample_surface(a, request.samples, seed=rng_seed)
    b_in_a = _inside_depths(a, np.asarray(b_points))
    a_in_b = _inside_depths(placed, np.asarray(a_points))
    if b_in_a.size == 0 and a_in_b.size == 0:
        return FitResult(ok=False, message="the parts could not be measured against each other")

    depths = np.concatenate([b_in_a, a_in_b])
    penetration = float(max(depths.max(), 0.0)) if depths.size else 0.0
    outside = -depths[depths < 0]
    clearance = float(outside.min()) if outside.size else None
    if exact_interference and penetration > TOUCH_MM:
        clearance = None  # meaningless while they overlap

    contact: Contact | None = None
    inside_b = np.asarray(b_points)[b_in_a > TOUCH_MM] if b_in_a.size else np.empty((0, 3))
    inside_a = np.asarray(a_points)[a_in_b > TOUCH_MM] if a_in_b.size else np.empty((0, 3))
    hits = np.vstack([inside_b, inside_a]) if (len(inside_b) or len(inside_a)) else None
    if hits is not None and len(hits):
        contact = Contact(
            bbox_min_mm=[round(float(v), 3) for v in hits.min(axis=0)],
            bbox_max_mm=[round(float(v), 3) for v in hits.max(axis=0)],
            points=int(len(hits)),
        )

    interference: float | None = None
    if penetration > TOUCH_MM:
        try:
            overlap = a.intersection(placed)
            interference = round(abs(float(overlap.volume)), 3) if not overlap.is_empty else 0.0
        except Exception:
            interference = None

    return FitResult(
        ok=True,
        verdict=verdict_for(penetration, clearance),
        max_penetration_mm=round(penetration, 3),
        min_clearance_mm=None if clearance is None else round(clearance, 3),
        b_inside_a_fraction=round(float(np.mean(b_in_a > TOUCH_MM)) if b_in_a.size else 0.0, 4),
        a_inside_b_fraction=round(float(np.mean(a_in_b > TOUCH_MM)) if a_in_b.size else 0.0, 4),
        interference_mm3=interference,
        contact=contact,
        a_bbox_mm=[[round(float(v), 3) for v in row] for row in a.bounds],
        b_bbox_mm=[[round(float(v), 3) for v in row] for row in placed.bounds],
        placement=request.placement,
    )


def _candidate_placements(a: trimesh.Trimesh, b: trimesh.Trimesh) -> list[tuple[str, Placement]]:
    """Useful deterministic assembly poses: nested centres and six touching faces."""
    labels = (
        (2, 1, "top"),
        (0, 1, "right"),
        (1, 1, "front"),
        (2, -1, "bottom"),
        (0, -1, "left"),
        (1, -1, "back"),
    )
    candidates: list[tuple[str, Placement]] = []
    for angle in (0.0, 90.0, 180.0, 270.0):
        rotated = place(a, b, Placement(rotate_z_deg=angle))
        a_size = a.bounds[1] - a.bounds[0]
        b_size = rotated.bounds[1] - rotated.bounds[0]
        candidates.append((f"centre · {angle:g}°", Placement(rotate_z_deg=angle)))
        for axis, sign, label in labels:
            offset = [0.0, 0.0, 0.0]
            offset[axis] = float(sign * (a_size[axis] + b_size[axis]) / 2)
            candidates.append(
                (f"{label} · {angle:g}°", Placement(offset_mm=tuple(offset), rotate_z_deg=angle))
            )
    return candidates


def auto_place(a: trimesh.Trimesh, b: trimesh.Trimesh, request: FitRequest) -> FitResult:
    """Pick a useful collision-free assembly pose and retain the best alternatives."""
    if a.is_empty or b.is_empty or len(a.faces) == 0 or len(b.faces) == 0:
        return FitResult(ok=False, message="both parts need faces to be assembled")
    ranked: list[tuple[tuple[float, ...], str, FitResult]] = []
    search_samples = min(request.samples, 800)
    for index, (label, placement) in enumerate(_candidate_placements(a, b)):
        measured = check_fit(
            a,
            b,
            FitRequest(placement=placement, samples=search_samples),
            exact_interference=False,
        )
        if not measured.ok or measured.verdict is None:
            continue
        penetration = measured.max_penetration_mm
        clearance = measured.min_clearance_mm if measured.min_clearance_mm is not None else 9999.0
        # A compatible nested pose is ideal. Otherwise prefer touching faces, then distance.
        compatible = measured.verdict in {"press", "transition", "sliding"}
        centred = placement.offset_mm == (0.0, 0.0, 0.0)
        score = (
            0.0 if compatible else 1.0 if measured.verdict == "loose" else 2.0,
            0.0 if centred and compatible else 1.0,
            penetration,
            clearance,
            float(index),
        )
        if measured.verdict == "collides":
            score = (3.0, 1.0, penetration, clearance, float(index))
        ranked.append((score, label, measured))
    if not ranked:
        return FitResult(ok=False, message="no assembly position could be measured")
    ranked.sort(key=lambda item: item[0])
    chosen = ranked[0][2].placement or Placement()
    result = check_fit(
        a,
        b,
        FitRequest(placement=chosen, samples=request.samples),
        exact_interference=True,
    )
    result.candidates = [
        AssemblyCandidate(
            label=label,
            placement=measured.placement or Placement(),
            verdict=measured.verdict or "apart",
            max_penetration_mm=measured.max_penetration_mm,
            min_clearance_mm=measured.min_clearance_mm,
        )
        for _, label, measured in ranked[:4]
    ]
    return result


def _load(source: Path, source_format: str) -> trimesh.Trimesh | None:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None:
        return None
    mesh = mesh.copy()
    mesh.merge_vertices()
    return mesh


def check_files(a: Path, a_format: str, b: Path, b_format: str, request: FitRequest) -> FitResult:
    mesh_a = _load(a, a_format)
    mesh_b = _load(b, b_format)
    if mesh_a is None or mesh_b is None:
        return FitResult(ok=False, message="one of the files has no mesh")
    if request.auto_place:
        return auto_place(mesh_a, mesh_b, request)
    return check_fit(mesh_a, mesh_b, request)


def run_in_sandbox(
    a: Path, a_format: str, b: Path, b_format: str, request: FitRequest, limits: Any | None = None
) -> FitResult:
    """Fit in the sandboxed child, like every other operation on an uploaded mesh."""
    from worker import sandbox

    chosen = limits or sandbox.DEFAULT_LIMITS
    try:
        if b.stat().st_size > chosen.max_input_bytes:
            return FitResult(ok=False, message="part B is larger than the sandbox allows")
    except OSError as exc:
        return FitResult(ok=False, message=str(exc))
    outcome = sandbox.run(
        "worker.fit",
        [a_format, str(a), b_format, str(b), request.model_dump_json()],
        input_path=a,
        limits=chosen,
    )
    if not outcome.ok:
        return FitResult(ok=False, message=outcome.message)
    return FitResult.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: fit <a_fmt> <a> <b_fmt> <b> <request-json>
    import sys

    a_format, a_path, b_format, b_path, payload = sys.argv[1:6]
    try:
        outcome = check_files(
            Path(a_path), a_format, Path(b_path), b_format, FitRequest.model_validate_json(payload)
        )
        print(json.dumps(outcome.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
