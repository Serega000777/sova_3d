"""F-014/F-076 (T-100 path): export a version to STL/3MF/GLB with the printable gate, download."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.jobs import runner
from app.models import Asset, Job, VersionAsset
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_printing_api import seed_version


def box_stl() -> bytes:
    exported = trimesh.creation.box(extents=(20, 10, 5)).export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


def open_box_stl() -> bytes:
    mesh = trimesh.creation.box(extents=(20, 10, 5))
    mesh.update_faces(np.asarray(mesh.face_normals)[:, 0] < 0.5)
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def run_all(db: Session, storage: S3Storage) -> list[Job]:
    done: list[Job] = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


@pytest.mark.parametrize("fmt", ["stl", "3mf", "glb"])
def test_export_creates_downloadable_asset(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    fmt: str,
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": fmt, "printable": fmt != "glb"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["format"] == fmt and result["report"]["status"] in ("pass", "warn")

    export_asset = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert export_asset is not None and export_asset.format == fmt
    cleanup_keys.append(export_asset.storage_key)
    assert db_session.get(VersionAsset, (version.id, export_asset.id, AssetRole.export)) is not None

    download = api_client.get(f"/api/v1/assets/{export_asset.id}/download", headers=actor.headers)
    assert download.status_code == 200
    body = download.json()
    assert body["format"] == fmt and body["byte_size"] == export_asset.byte_size
    fetched = httpx.get(body["url"])
    assert fetched.status_code == 200 and len(fetched.content) == export_asset.byte_size
    loaded = trimesh.load(trimesh.util.wrap_as_stream(fetched.content), file_type=fmt, force="mesh")
    assert isinstance(loaded, trimesh.Trimesh)
    scale = 1000.0 if fmt == "glb" else 1.0
    assert loaded.volume * scale**3 == pytest.approx(1000.0, rel=1e-4)


def test_printable_gate_blocks_open_mesh_export(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, open_box_stl())
    cleanup_keys.append(asset.storage_key)
    api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "stl", "printable": True},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert job.error is not None and job.error["code"] == "export_blocked"
    assert "Not print-ready" in job.error["message"]
    checks = {c["id"]: c["status"] for c in job.error["details"]["report"]["checks"]}
    assert checks["printable_topology"] == "fail"
    assert not [
        link
        for link in db_session.query(VersionAsset).filter_by(version_id=version.id)
        if link.role is AssetRole.export
    ]


def test_download_is_workspace_scoped(
    api_client: TestClient, db_session: Session, storage: S3Storage, cleanup_keys: list[str]
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    _, _, asset = seed_version(db_session, storage, owner, box_stl())
    cleanup_keys.append(asset.storage_key)
    assert (
        api_client.get(f"/api/v1/assets/{asset.id}/download", headers=owner.headers).status_code
        == 200
    )
    assert (
        api_client.get(f"/api/v1/assets/{asset.id}/download", headers=stranger.headers).status_code
        == 404
    )
