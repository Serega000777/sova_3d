"""F-043: compare a design with an accepted metric post-print scan."""

import hashlib
import uuid
from typing import Any, cast

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — register physical_compare
from app.jobs import runner
from app.models.core import Units
from app.models.execution import JobStatus
from app.models.scanning import ScanMode, ScanSession, ScanStatus
from app.models.versioning import Asset, AssetKind, AssetRole
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import project  # noqa: F401


def _asset(db: Session, storage: S3Storage, actor: Actor, mesh: trimesh.Trimesh) -> Asset:
    data = cast(bytes, mesh.export(file_type="stl"))
    digest = hashlib.sha256(data).hexdigest()
    key = storage.object_key(actor.workspace.id, digest, "stl")
    storage.put(key, data, "model/stl")
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=digest,
        storage_key=key,
        mime="model/stl",
        format="stl",
        byte_size=len(data),
        units=Units.mm,
        metadata_={"test": "physical_comparison"},
        created_by=actor.user.id,
    )
    db.add(asset)
    db.flush()
    return asset


def test_metric_scan_is_registered_and_compared_without_scaling(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    design_mesh = trimesh.creation.box(extents=(40.0, 20.0, 10.0))
    scan_mesh = trimesh.creation.box(extents=(41.0, 20.0, 10.0))
    angle = np.radians(17)
    pose = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0.0, 0.0],
            [np.sin(angle), np.cos(angle), 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    pose[:3, 3] = [80.0, -30.0, 12.0]
    scan_mesh.apply_transform(pose)
    design_asset = _asset(db_session, storage, actor, design_mesh)
    scan_asset = _asset(db_session, storage, actor, scan_mesh)
    design = projects.create_version_internal(
        db_session,
        project_id=uuid.UUID(project),
        label="Digital design",
        assets={AssetRole.model: design_asset.id},
        created_by=actor.user.id,
    )
    scan = projects.create_version_internal(
        db_session,
        project_id=uuid.UUID(project),
        label="Metric scan of print",
        assets={AssetRole.model: scan_asset.id},
        created_by=actor.user.id,
    )
    session = ScanSession(
        workspace_id=actor.workspace.id,
        project_id=design.project_id,
        created_by=actor.user.id,
        status=ScanStatus.accepted,
        mode=ScanMode.rgb,
        capabilities={"subject": "object", "metric_scale": "none"},
        mesh_asset_id=scan_asset.id,
        result_version_id=scan.id,
    )
    db_session.add(session)
    db_session.flush()

    body: dict[str, Any] = {"scan_version_id": str(scan.id), "tolerance_mm": 0.2, "samples": 500}
    unmeasured = api_client.post(
        f"/api/v1/models/{design.id}/physical-comparisons",
        json=body,
        headers=actor.headers,
    )
    assert unmeasured.status_code == 422

    session.mode = ScanMode.scanner
    session.capabilities = {"subject": "object", "metric_scale": "scanner"}
    db_session.flush()
    accepted = api_client.post(
        f"/api/v1/models/{design.id}/physical-comparisons",
        json=body,
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    report = result["report"]
    assert result["scan_session_id"] == str(session.id)
    assert report["scale_locked"] is True
    assert max(abs(value) for value in report["size_error_mm"]) == pytest.approx(1.0, abs=0.05)
    assert report["p95_mm"] > 0.2
    assert report["within_tolerance"] < 1.0
