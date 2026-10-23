"""F-043: a metric scan is rigidly registered without hiding size error."""

import numpy as np
import pytest
import trimesh

from worker.metrology import compare


def test_rigid_registration_recovers_pose_without_scaling() -> None:
    design = trimesh.creation.box(extents=(40.0, 20.0, 10.0))
    scan = design.copy()
    pose = trimesh.transformations.rotation_matrix(np.radians(31), [0, 0, 1])
    pose[:3, 3] = [120.0, -45.0, 18.0]
    scan.apply_transform(pose)

    result = compare(design, scan, tolerance_mm=0.2, samples=500)

    assert result.ok
    assert result.p95_mm < 0.01
    assert result.within_tolerance == 1.0
    assert result.scale_locked is True
    assert result.scan_size_mm == pytest.approx(result.design_size_mm, abs=0.01)


def test_metric_size_error_is_reported_instead_of_scaled_away() -> None:
    design = trimesh.creation.box(extents=(40.0, 20.0, 10.0))
    scan = trimesh.creation.box(extents=(41.0, 20.0, 10.0))

    result = compare(design, scan, tolerance_mm=0.2, samples=500)

    assert result.ok
    assert max(abs(value) for value in result.size_error_mm) == pytest.approx(1.0, abs=0.02)
    assert result.p95_mm > 0.2
    assert result.within_tolerance < 1.0
