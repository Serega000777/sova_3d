"""Metric post-print scan registration and deviation measurement (F-043)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from worker.features import _load, deviation


class PhysicalComparison(BaseModel):
    ok: bool
    message: str | None = None
    registration_transform: list[float] = Field(default_factory=list)
    registration_rms_mm: float = 0.0
    tolerance_mm: float = 0.2
    mean_mm: float = 0.0
    p95_mm: float = 0.0
    max_mm: float = 0.0
    within_tolerance: float = 0.0
    samples: int = 0
    design_size_mm: list[float] = Field(default_factory=list)
    scan_size_mm: list[float] = Field(default_factory=list)
    size_error_mm: list[float] = Field(default_factory=list)
    scale_locked: bool = True


def compare(
    design: trimesh.Trimesh,
    scan: trimesh.Trimesh,
    *,
    tolerance_mm: float,
    samples: int = 3000,
) -> PhysicalComparison:
    """Rigidly register a metric scan to CAD, never scaling away manufacturing error."""
    if design.is_empty or scan.is_empty:
        return PhysicalComparison(ok=False, message="a mesh is empty")
    transform, cost = trimesh.registration.mesh_other(
        scan,
        design,
        samples=min(samples, 5000),
        scale=False,
        reflection=False,
        seed=17,
    )
    measured = deviation(scan, design, transform, tolerance_mm, samples=samples)
    if not measured.ok:
        return PhysicalComparison(ok=False, message=measured.message)
    placed = scan.copy()
    placed.apply_transform(transform)
    design_size = np.asarray(design.extents, dtype=float)
    scan_size = np.asarray(placed.extents, dtype=float)
    return PhysicalComparison(
        ok=True,
        registration_transform=np.asarray(transform, dtype=float).reshape(-1).round(9).tolist(),
        registration_rms_mm=round(math.sqrt(max(float(cost), 0.0)), 4),
        tolerance_mm=measured.tolerance_mm,
        mean_mm=measured.mean_mm,
        p95_mm=measured.p95_mm,
        max_mm=measured.max_mm,
        within_tolerance=measured.within_tolerance,
        samples=measured.samples,
        design_size_mm=design_size.round(3).tolist(),
        scan_size_mm=scan_size.round(3).tolist(),
        size_error_mm=(scan_size - design_size).round(3).tolist(),
    )


def compare_files(
    design_path: Path,
    scan_path: Path,
    tolerance_mm: float,
    samples: int,
) -> PhysicalComparison:
    design = _load(design_path, "stl")
    scan = _load(scan_path, "stl")
    if design is None or scan is None:
        return PhysicalComparison(ok=False, message="a mesh is missing")
    return compare(design, scan, tolerance_mm=tolerance_mm, samples=samples)


def compare_in_sandbox(
    design_path: Path,
    scan_path: Path,
    tolerance_mm: float,
    samples: int,
    limits: Any | None = None,
) -> PhysicalComparison:
    from worker import sandbox

    outcome = sandbox.run(
        "worker.metrology",
        [str(design_path), str(scan_path), str(tolerance_mm), str(samples)],
        input_path=design_path,
        limits=limits or sandbox.DEFAULT_LIMITS,
    )
    if not outcome.ok:
        return PhysicalComparison(ok=False, message=outcome.message)
    return PhysicalComparison.model_validate(outcome.output)


if __name__ == "__main__":
    import sys

    try:
        result = compare_files(
            Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
        )
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
