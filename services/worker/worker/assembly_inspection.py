"""Bounded world-space envelope inspection for immutable multi-object scenes.

This is deliberately a broad-phase geometry check.  It measures every visible mesh after
applying the exact saved world transform and reports overlapping axis-aligned envelopes.  An
envelope overlap is a candidate for closer inspection, never a collision/contact verdict.
"""

from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from worker import fit, sandbox


class ComponentInput(BaseModel):
    node_id: str
    path: str
    format: Literal["stl", "glb"]
    world_transform: list[list[float]]


class InspectionRequest(BaseModel):
    version_id: str
    components: list[ComponentInput] = Field(min_length=1, max_length=64)


class ComponentEnvelope(BaseModel):
    node_id: str
    bbox_min_mm: list[float]
    bbox_max_mm: list[float]


class EnvelopeOverlap(BaseModel):
    node_a_id: str
    node_b_id: str
    overlap_mm: list[float]


class InspectionResult(BaseModel):
    ok: bool
    version_id: str
    component_count: int = 0
    scene_bbox_min_mm: list[float] = Field(default_factory=list)
    scene_bbox_max_mm: list[float] = Field(default_factory=list)
    components: list[ComponentEnvelope] = Field(default_factory=list)
    envelope_overlaps: list[EnvelopeOverlap] = Field(default_factory=list)
    collision_status: Literal["not_checked"] = "not_checked"
    constraints_status: Literal["not_modeled"] = "not_modeled"
    message: str | None = None
    limitations: list[str] = Field(default_factory=list)


def inspect(request: InspectionRequest) -> InspectionResult:
    envelopes: list[ComponentEnvelope] = []
    bounds: dict[str, np.ndarray] = {}
    for component in request.components:
        mesh = fit._load(Path(component.path), component.format)  # noqa: SLF001
        if mesh is None or mesh.is_empty or len(mesh.faces) == 0:
            return InspectionResult(
                ok=False,
                version_id=request.version_id,
                message=f"scene node {component.node_id} has no measurable mesh",
            )
        matrix = np.asarray(component.world_transform, dtype=float)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            return InspectionResult(
                ok=False,
                version_id=request.version_id,
                message=f"scene node {component.node_id} has an invalid world transform",
            )
        moved = mesh.copy()
        moved.apply_transform(matrix)
        measured = np.asarray(moved.bounds, dtype=float)
        if measured.shape != (2, 3) or not np.isfinite(measured).all():
            return InspectionResult(
                ok=False,
                version_id=request.version_id,
                message=f"scene node {component.node_id} has invalid world bounds",
            )
        bounds[component.node_id] = measured
        envelopes.append(
            ComponentEnvelope(
                node_id=component.node_id,
                bbox_min_mm=[round(float(value), 6) for value in measured[0]],
                bbox_max_mm=[round(float(value), 6) for value in measured[1]],
            )
        )

    overlaps: list[EnvelopeOverlap] = []
    for left, right in combinations(request.components, 2):
        overlap = np.minimum(bounds[left.node_id][1], bounds[right.node_id][1]) - np.maximum(
            bounds[left.node_id][0], bounds[right.node_id][0]
        )
        if bool(np.all(overlap > 0.0)):
            overlaps.append(
                EnvelopeOverlap(
                    node_a_id=left.node_id,
                    node_b_id=right.node_id,
                    overlap_mm=[round(float(value), 6) for value in overlap],
                )
            )

    all_bounds = np.stack(list(bounds.values()))
    scene_min = np.min(all_bounds[:, 0, :], axis=0)
    scene_max = np.max(all_bounds[:, 1, :], axis=0)
    if any(not math.isfinite(float(value)) for value in (*scene_min, *scene_max)):
        return InspectionResult(
            ok=False,
            version_id=request.version_id,
            message="scene bounds are not finite",
        )
    return InspectionResult(
        ok=True,
        version_id=request.version_id,
        component_count=len(envelopes),
        scene_bbox_min_mm=[round(float(value), 6) for value in scene_min],
        scene_bbox_max_mm=[round(float(value), 6) for value in scene_max],
        components=envelopes,
        envelope_overlaps=overlaps,
        limitations=[
            "axis-aligned envelope overlap is a broad-phase candidate, "
            "not mesh collision or contact",
            "mate and joint constraints, motion, gravity, friction and structural loads "
            "are not modeled",
        ],
    )


def run_in_sandbox(manifest: Path) -> InspectionResult:
    outcome = sandbox.run(
        "worker.assembly_inspection",
        [str(manifest)],
        input_path=manifest,
        cwd=manifest.parent,
    )
    if not outcome.ok or outcome.output is None:
        return InspectionResult(
            ok=False,
            version_id="unknown",
            message=outcome.message or "assembly inspection failed",
        )
    return InspectionResult.model_validate(outcome.output)


if __name__ == "__main__":
    import sys

    try:
        payload = InspectionRequest.model_validate_json(Path(sys.argv[1]).read_text())
        print(json.dumps(inspect(payload).model_dump(mode="json")))
    except Exception as exc:
        print(json.dumps({"ok": False, "version_id": "unknown", "message": str(exc)}))
        raise SystemExit(1) from exc
