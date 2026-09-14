"""T-031: repair job endpoint -> runner -> new asset + child version."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers the repair handler
from app.jobs import runner
from app.models import Asset, Job, JobArtifact, Project, ProjectVersion
from app.models.core import Units
from app.models.execution import FailureClass, JobStatus
from app.models.versioning import AssetKind, AssetRole, VersionState
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


def open_box_stl() -> bytes:
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 5.0))
    mesh.update_faces(np.asarray(mesh.face_normals)[:, 0] < 0.5)  # drop the +X side
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


def seed_version(
    db: Session, storage: S3Storage, actor: Actor, payload: bytes, fmt: str = "stl"
) -> tuple[Project, ProjectVersion, Asset]:
    project = projects.create_project(
        db, user_id=actor.user.id, workspace_id=actor.workspace.id, name="repair-me"
    )
    sha = hashlib.sha256(payload).hexdigest()
    key = S3Storage.object_key(actor.workspace.id, sha, fmt)
    storage.put(key, payload, "model/stl")
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=sha,
        storage_key=key,
        mime="model/stl",
        format=fmt,
        byte_size=len(payload),
        units=Units.mm,
    )
    db.add(asset)
    db.flush()
    version = projects.create_version(
        db,
        user_id=actor.user.id,
        project_id=project.id,
        assets={AssetRole.source: asset.id},
        label="upload",
    )
    return project, version, asset


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def test_repair_enqueues_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(db_session, storage, actor, open_box_stl())
    cleanup_keys.append(asset.storage_key)

    response = api_client.post(
        f"/api/v1/models/{version.id}/repair",
        headers={**actor.headers, "Idempotency-Key": "repair-1"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued" and body["type"] == "repair"
    assert body["project_version_id"] == str(version.id)

    again = api_client.post(
        f"/api/v1/models/{version.id}/repair",
        headers={**actor.headers, "Idempotency-Key": "repair-1"},
    )
    assert again.json()["job_id"] == body["job_id"]

    job = db_session.get(Job, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.input == {"version_id": str(version.id), "asset_id": str(asset.id)}
    assert job.project_id == project.id and job.created_by == actor.user.id

    polled = api_client.get(f"/api/v1/jobs/{job.id}", headers=actor.headers)
    assert polled.status_code == 200
    assert polled.json()["progress"] == 0 and polled.json()["result"] is None


def test_runner_repairs_and_creates_child_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(db_session, storage, actor, open_box_stl())
    cleanup_keys.append(asset.storage_key)
    job_id = api_client.post(f"/api/v1/models/{version.id}/repair", headers=actor.headers).json()[
        "job_id"
    ]

    progress_log: list[tuple[int, str | None]] = []

    def commit() -> None:
        db_session.flush()
        job = db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        progress_log.append((job.progress, job.stage))

    done = runner.run_once(db_session, storage, commit=commit)
    assert done is not None and done.id == uuid.UUID(job_id)
    assert done.status is JobStatus.succeeded, done.error
    assert done.progress == 100 and done.finished_at is not None
    assert [p for p, _ in progress_log] == sorted(p for p, _ in progress_log)  # monotonic
    assert "downloaded" in {s for _, s in progress_log}

    result = done.result or {}
    new_version = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert new_version is not None
    assert new_version.parent_version_id == version.id
    assert new_version.state is VersionState.finalized and new_version.label == "Repair"
    assert new_version.provenance["job_id"] == job_id
    assert new_version.provenance["repair_report"]["after"]["watertight"] is True
    assert new_version.provenance["repair_report"]["delta"]["holes_closed"] == 1

    new_asset = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert new_asset is not None and new_asset.kind is AssetKind.derived
    assert new_asset.metadata_["derived_from"] == str(asset.id)
    assert new_asset.units is Units.mm
    cleanup_keys.append(new_asset.storage_key)
    repaired = storage.get(new_asset.storage_key)
    assert hashlib.sha256(repaired).hexdigest() == new_asset.sha256
    mesh = trimesh.load(trimesh.util.wrap_as_stream(repaired), file_type="stl", force="mesh")
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight and mesh.volume == pytest.approx(1000.0)

    db_session.refresh(project)
    assert project.head_version_id == new_version.id
    assert db_session.get(JobArtifact, (done.id, new_asset.id, "model")) is not None

    polled = api_client.get(f"/api/v1/jobs/{job_id}", headers=actor.headers).json()
    assert polled["status"] == "succeeded" and polled["result"]["version_id"] == str(new_version.id)

    # The source asset is untouched and still attached to the original version.
    assert storage.get(asset.storage_key) == open_box_stl()
    lineage = api_client.get(
        f"/api/v1/versions/{new_version.id}/lineage", headers=actor.headers
    ).json()
    assert [v["sequence_no"] for v in lineage] == [2, 1]


def test_repair_failure_is_recorded_without_new_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(
        db_session, storage, actor, b"solid nothing\nendsolid nothing\n"
    )
    cleanup_keys.append(asset.storage_key)
    job_id = api_client.post(f"/api/v1/models/{version.id}/repair", headers=actor.headers).json()[
        "job_id"
    ]

    done = runner.run_once(db_session, storage, commit=db_session.flush)
    assert done is not None and done.status is JobStatus.failed
    assert done.failure_class is FailureClass.permanent
    assert done.error is not None and done.error["code"] == "repair_failed"
    assert done.finished_at is not None

    versions = api_client.get(
        f"/api/v1/projects/{project.id}/versions", headers=actor.headers
    ).json()
    assert len(versions) == 1
    polled = api_client.get(f"/api/v1/jobs/{job_id}", headers=actor.headers).json()
    assert polled["status"] == "failed" and polled["error"]["code"] == "repair_failed"


def test_repair_requires_mesh_asset_and_membership(
    api_client: TestClient, db_session: Session, storage: S3Storage, cleanup_keys: list[str]
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    project = projects.create_project(
        db_session, user_id=owner.user.id, workspace_id=owner.workspace.id, name="empty"
    )
    empty_version = projects.create_version(
        db_session, user_id=owner.user.id, project_id=project.id
    )
    response = api_client.post(f"/api/v1/models/{empty_version.id}/repair", headers=owner.headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"

    _, version, asset = seed_version(db_session, storage, owner, open_box_stl())
    cleanup_keys.append(asset.storage_key)
    foreign = api_client.post(f"/api/v1/models/{version.id}/repair", headers=stranger.headers)
    assert foreign.status_code == 404
    job_id = api_client.post(f"/api/v1/models/{version.id}/repair", headers=owner.headers).json()[
        "job_id"
    ]
    assert api_client.get(f"/api/v1/jobs/{job_id}", headers=stranger.headers).status_code == 404


def test_runner_is_idle_without_jobs(db_session: Session, storage: S3Storage) -> None:
    assert runner.run_once(db_session, storage, commit=db_session.flush) is None
