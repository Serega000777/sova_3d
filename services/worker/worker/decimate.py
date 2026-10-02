"""Mesh decimation (T-083/F-002 scan quality presets), shared by game-ready export and scans.

`QUALITY_WEIGHTS` mirrors `QUALITY_PRESETS` in `packages/contracts/src/create-scenarios.ts`:
the same preset ids and the same rough share of the heaviest option's triangles.
"""

from __future__ import annotations

import trimesh

QUALITY_WEIGHTS: dict[str, float] = {
    "fast": 0.1,
    "default": 0.3,
    "dense": 0.7,
    "raw": 1.0,
}
DEFAULT_QUALITY = "default"


def decimated(mesh: trimesh.Trimesh, faces: int) -> trimesh.Trimesh:
    if len(mesh.faces) <= faces:
        return mesh.copy()
    return mesh.simplify_quadric_decimation(face_count=max(int(faces), 4))
