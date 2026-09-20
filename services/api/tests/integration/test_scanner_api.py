"""E31 (F-082): a dedicated 3D scanner streams metric fragments; they fuse into a model."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.models.versioning import ProjectVersion
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import run_all, upload

DEVICE = {
    "device": {
        "kind": "scanner",
        "vendor": "Simulated",
        "model": "Turntable 1",
        "driver": "simulated",
        "accuracy_mm": 0.05,
    }
}


def stl(mesh: trimesh.Trimesh) -> bytes:
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else str(exported).encode()


def start_scanner_session(api_client: TestClient, actor: Actor, **extra: Any) -> dict[str, Any]:
    response = api_client.post(
        "/api/v1/scans",
        json={
            "workspace_id": str(actor.workspace.id),
            "mode": "scanner",
            "label": "bracket on the turntable",
            "capabilities": DEVICE,
            **extra,
        },
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    session: dict[str, Any] = response.json()
    return session


def test_scanner_fragments_fuse_into_a_metric_model(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "scanner"},
        headers=actor.headers,
    ).json()["id"]
    scan = start_scanner_session(api_client, actor, project_id=project_id)
    assert scan["mode"] == "scanner" and scan["capabilities"]["device"]["vendor"] == "Simulated"

    # two overlapping halves of an 80 x 40 x 20 bracket, as the scanner software delivers them
    left = trimesh.creation.box(extents=(44, 40, 20))
    left.apply_translation((22, 20, 10))
    right = trimesh.creation.box(extents=(44, 40, 20))
    right.apply_translation((58, 20, 10))
    for index, half in enumerate((left, right)):
        asset_id = upload(api_client, actor, stl(half), f"fragment_{index}.stl", "model/stl")
        added = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": asset_id,
                "sequence_no": index,
                "kind": "mesh",
                "pose": {"matrix": np.eye(4).tolist()},
                "quality": {"points": 12000},
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text
    stats = api_client.patch(
        f"/api/v1/scans/{scan['id']}/capture-stats",
        json={"stats": {"fragments": 2, "coverage": 1.0}},
        headers=actor.headers,
    )
    assert stats.status_code == 200 and stats.json()["frame_count"] == 2

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    report = ready["report"]
    assert report["provider"] == "fusion" and report["fusion"] == "union"
    assert report["scale"]["source"] == "device" and report["scale"]["confidence"] >= 0.95
    assert report["scale"]["applied_mm"] == 80.0

    kept = api_client.post(
        f"/api/v1/scans/{scan['id']}/accept",
        json={"label": "Scanned bracket"},
        headers=actor.headers,
    )
    assert kept.status_code == 200, kept.text
    version = db_session.get(ProjectVersion, uuid.UUID(kept.json()["result_version_id"]))
    assert version is not None and version.label == "Scanned bracket"
    assert version.provenance["operation"] == "scan" and version.provenance["mode"] == "scanner"
    assert version.provenance["report"]["scale"]["source"] == "device"


def test_a_scanner_session_accepts_one_fused_mesh_and_refuses_photos_as_fragments(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    scan = start_scanner_session(api_client, actor)
    whole = trimesh.creation.box(extents=(50, 20, 10))
    asset_id = upload(api_client, actor, stl(whole), "whole.stl", "model/stl")
    # a mesh file cannot pose as a photo frame...
    wrong = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "rgb"},
        headers=actor.headers,
    )
    assert wrong.status_code == 422
    # ...and a single fused mesh is a complete scanner session
    added = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "mesh"},
        headers=actor.headers,
    )
    assert added.status_code == 201, added.text
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": "80"},  # the user's guess; the scanner knows better
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["report"]["scale"]["applied_mm"] == 50.0
    assert "80" in ready["report"]["scale"]["warning"]


def test_a_demo_scan_feeds_a_scanner_session_and_reconstructs(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    """F-082 without a device: the server's simulated turntable delivers the fragments."""
    response = api_client.post(
        "/api/v1/scans/demo",
        json={"workspace_id": str(actor.workspace.id), "label": "demo bracket"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["scan"]["mode"] == "scanner" and body["job"]["type"] == "demo_scan"
    scan_id = body["scan"]["id"]

    # the demo job (no pause in tests) adds eight fragments and finalizes; then reconstruction
    from app.models.execution import Job

    demo = db_session.get(Job, uuid.UUID(body["job"]["job_id"]))
    assert demo is not None
    demo.input = {**demo.input, "pause_s": 0}
    db_session.flush()
    done = run_all(db_session, storage)
    assert [job.type for job in done] == ["demo_scan", "reconstruct_scan"]
    assert all(job.status is JobStatus.succeeded for job in done), [j.error for j in done]

    scan = api_client.get(f"/api/v1/scans/{scan_id}", headers=actor.headers).json()
    assert scan["frame_count"] == 8 and scan["status"] == "ready"
    assert scan["capture_stats"]["fragments"] == 8
    frames = api_client.get(f"/api/v1/scans/{scan_id}/frames", headers=actor.headers).json()
    assert scan["capture_stats"]["faces"] == sum(frame["quality"]["faces"] for frame in frames)
    report = scan["report"]
    assert report["scale"]["source"] == "device"
    assert abs(report["scale"]["applied_mm"] - 120) < 1
    project = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Demo bracket"},
        headers=actor.headers,
    )
    assert project.status_code == 201
    kept = api_client.post(
        f"/api/v1/scans/{scan_id}/accept",
        json={"project_id": project.json()["id"]},
        headers=actor.headers,
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["result_version_id"] is not None


def test_canceled_demo_does_not_add_fragments(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    response = api_client.post(
        "/api/v1/scans/demo",
        json={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert response.status_code == 202
    scan_id = response.json()["scan"]["id"]
    canceled = api_client.post(f"/api/v1/scans/{scan_id}/cancel", headers=actor.headers)
    assert canceled.status_code == 200
    done = run_all(db_session, storage)
    assert len(done) == 1 and done[0].status is JobStatus.succeeded
    scan = api_client.get(f"/api/v1/scans/{scan_id}", headers=actor.headers).json()
    assert scan["status"] == "canceled" and scan["frame_count"] == 0
    assert scan["mesh_asset_id"] is None
