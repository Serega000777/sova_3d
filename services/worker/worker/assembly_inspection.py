"""Bounded world-space collision inspection for immutable multi-object scenes.

Every visible mesh is measured after its exact saved world transform. Axis-aligned envelopes
form the broad phase; only positive-volume envelope candidates reach the Manifold boolean
engine. Touching alone is deliberately not reported as a collision.
"""

from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
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


class MeshCollision(BaseModel):
    node_a_id: str
    node_b_id: str
    interference_mm3: float
    bbox_min_mm: list[float]
    bbox_max_mm: list[float]


class CollisionUnavailable(BaseModel):
    node_a_id: str
    node_b_id: str
    reason: Literal["non_watertight", "boolean_failed", "candidate_limit"]


class InspectionResult(BaseModel):
    ok: bool
    version_id: str
    component_count: int = 0
    scene_bbox_min_mm: list[float] = Field(default_factory=list)
    scene_bbox_max_mm: list[float] = Field(default_factory=list)
    components: list[ComponentEnvelope] = Field(default_factory=list)
    envelope_overlaps: list[EnvelopeOverlap] = Field(default_factory=list)
    mesh_collisions: list[MeshCollision] = Field(default_factory=list)
    collision_unavailable_pairs: list[CollisionUnavailable] = Field(default_factory=list)
    collision_status: Literal["checked", "unavailable"] = "unavailable"
    constraints_status: Literal["not_modeled"] = "not_modeled"
    message: str | None = None
    limitations: list[str] = Field(default_factory=list)


MAX_EXACT_COLLISION_PAIRS = 128
MIN_INTERFERENCE_MM3 = 1e-6


def inspect(request: InspectionRequest) -> InspectionResult:
    envelopes: list[ComponentEnvelope] = []
    bounds: dict[str, np.ndarray] = {}
    meshes: dict[str, trimesh.Trimesh] = {}
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
        meshes[component.node_id] = moved
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
    candidates: list[tuple[str, str]] = []
    for left, right in combinations(request.components, 2):
        overlap = np.minimum(bounds[left.node_id][1], bounds[right.node_id][1]) - np.maximum(
            bounds[left.node_id][0], bounds[right.node_id][0]
        )
        if bool(np.all(overlap > 0.0)):
            candidates.append((left.node_id, right.node_id))
            overlaps.append(
                EnvelopeOverlap(
                    node_a_id=left.node_id,
                    node_b_id=right.node_id,
                    overlap_mm=[round(float(value), 6) for value in overlap],
                )
            )

    collisions: list[MeshCollision] = []
    unavailable: list[CollisionUnavailable] = []
    if len(candidates) > MAX_EXACT_COLLISION_PAIRS:
        unavailable = [
            CollisionUnavailable(
                node_a_id=left_id,
                node_b_id=right_id,
                reason="candidate_limit",
            )
            for left_id, right_id in candidates
        ]
    else:
        for left_id, right_id in candidates:
            left_mesh = meshes[left_id]
            right_mesh = meshes[right_id]
            if not left_mesh.is_watertight or not right_mesh.is_watertight:
                unavailable.append(
                    CollisionUnavailable(
                        node_a_id=left_id,
                        node_b_id=right_id,
                        reason="non_watertight",
                    )
                )
                continue
            try:
                intersection = left_mesh.intersection(
                    right_mesh,
                    engine="manifold",
                )
                if intersection.is_empty:
                    continue
                volume = abs(float(intersection.volume))
                measured = np.asarray(intersection.bounds, dtype=float)
            except Exception:
                unavailable.append(
                    CollisionUnavailable(
                        node_a_id=left_id,
                        node_b_id=right_id,
                        reason="boolean_failed",
                    )
                )
                continue
            if volume <= MIN_INTERFERENCE_MM3:
                continue
            if (
                not math.isfinite(volume)
                or measured.shape != (2, 3)
                or not np.isfinite(measured).all()
            ):
                unavailable.append(
                    CollisionUnavailable(
                        node_a_id=left_id,
                        node_b_id=right_id,
                        reason="boolean_failed",
                    )
                )
                continue
            collisions.append(
                MeshCollision(
                    node_a_id=left_id,
                    node_b_id=right_id,
                    interference_mm3=round(volume, 6),
                    bbox_min_mm=[round(float(value), 6) for value in measured[0]],
                    bbox_max_mm=[round(float(value), 6) for value in measured[1]],
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
        mesh_collisions=collisions,
        collision_unavailable_pairs=unavailable,
        collision_status="unavailable" if unavailable else "checked",
        limitations=[
            "mesh collision means positive-volume Manifold intersection; "
            "touching alone is not a hit",
            "non-watertight geometry, boolean failures or more than 128 broad-phase candidates "
            "make the collision result unavailable instead of passing it",
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
