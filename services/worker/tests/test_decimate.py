"""Scan quality presets (F-002): decimation weight mirrors the contracts' QUALITY_PRESETS."""

from __future__ import annotations

import trimesh

from worker.decimate import QUALITY_WEIGHTS, decimated


def test_quality_weights_mirror_the_contracts_presets() -> None:
    # packages/contracts/src/create-scenarios.ts QUALITY_PRESETS: fast/default/dense/raw weights.
    assert QUALITY_WEIGHTS == {"fast": 0.1, "default": 0.3, "dense": 0.7, "raw": 1.0}


def test_decimation_reduces_faces_proportionally_to_weight() -> None:
    sphere = trimesh.creation.icosphere(subdivisions=4)  # 5120 faces
    native = len(sphere.faces)
    for _quality, weight in QUALITY_WEIGHTS.items():
        if weight >= 1.0:
            continue
        target = round(native * weight)
        result = decimated(sphere, target)
        assert len(result.faces) == target
        assert len(result.faces) < native


def test_raw_weight_means_no_simplification() -> None:
    sphere = trimesh.creation.icosphere(subdivisions=4)
    native = len(sphere.faces)
    target = round(native * QUALITY_WEIGHTS["raw"])
    assert target == native
    result = decimated(sphere, target)
    assert len(result.faces) == native  # at or under the target: `decimated` copies, not simplifies


def test_a_mesh_already_under_the_target_is_left_alone() -> None:
    cube = trimesh.creation.box(extents=(20.0, 20.0, 20.0))  # 12 faces
    result = decimated(cube, 1000)
    assert len(result.faces) == 12
    assert result is not cube  # a copy, same contract as the rest of the pipeline
