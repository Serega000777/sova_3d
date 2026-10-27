"""F-014/F-076 (T-100 path): export a version to STL/3MF/GLB with the printable gate, download."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

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
from app.services import jobs
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


def test_export_creates_a_metric_usdz_for_system_ar_preview(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "usdz"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["format"] == "usdz"
    assert result["report"]["status"] in ("pass", "warn")
    checks = {check["id"]: check["status"] for check in result["report"]["checks"]}
    assert checks["units_explicit"] == "pass"
    assert checks["volume"] == "pass"

    exported = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert exported is not None and exported.format == "usdz"
    cleanup_keys.append(exported.storage_key)
    assert storage.get(exported.storage_key).startswith(b"PK")


@pytest.mark.parametrize("fmt", ["obj", "ply", "dae", "x3d", "wrl"])
def test_exchange_export_uses_the_existing_validated_converter(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    fmt: str,
) -> None:
    _, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": fmt},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["format"] == fmt
    assert result["report"]["status"] in ("pass", "warn")

    exported = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert exported is not None and exported.format == fmt
    cleanup_keys.append(exported.storage_key)
    data = storage.get(exported.storage_key)
    expected_markers = {
        "obj": (b"\nv ", b"\nf "),
        "ply": (b"ply\n", b"end_header\n"),
        "dae": (b"<COLLADA",),
        "x3d": (b"<X3D", b"<IndexedFaceSet"),
        "wrl": (b"#VRML V2.0", b"IndexedFaceSet"),
    }
    assert all(marker in data for marker in expected_markers[fmt])


def test_scene_export_uses_stored_visibility_instances_and_world_transforms(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    moved = np.eye(4)
    moved[0, 3] = 40
    hidden = np.eye(4)
    hidden[1, 3] = 100
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "part",
                    "name": "Part",
                    "kind": "object",
                    "asset_id": str(asset.id),
                },
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "part",
                    "transform": moved.tolist(),
                },
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "instance_of": "part",
                    "visible": False,
                    "transform": hidden.tolist(),
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    scene_version = scene.json()["version_id"]
    accepted = api_client.post(
        f"/api/v1/models/{scene_version}/exports",
        json={"format": "stl"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["report"]["scene"] == {
        "visible_objects": 2,
        "asset_ids": [str(asset.id), str(asset.id)],
        "transforms_applied": True,
    }
    exported = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert exported is not None
    cleanup_keys.append(exported.storage_key)
    made = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(exported.storage_key)),
        file_type="stl",
        force="mesh",
    )
    assert isinstance(made, trimesh.Trimesh)
    np.testing.assert_allclose(made.bounds, [[-10, -5, -2.5], [50, 5, 2.5]])
    assert made.volume == pytest.approx(2000)


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


def test_latest_integrity_report_is_version_scoped_persisted_and_authorized(
    api_client: TestClient,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    _, version, source = seed_version(db_session, storage, owner, box_stl())
    cleanup_keys.append(source.storage_key)

    missing = api_client.get(f"/api/v1/models/{version.id}/integrity-report", headers=owner.headers)
    assert missing.status_code == 404
    missing_pdf = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report.pdf", headers=owner.headers
    )
    assert missing_pdf.status_code == 404

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "glb", "printable": False},
        headers=owner.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    export_asset = db_session.get(Asset, uuid.UUID((job.result or {})["asset_id"]))
    assert export_asset is not None
    cleanup_keys.append(export_asset.storage_key)

    restored = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report", headers=owner.headers
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["job_id"] == str(job.id)
    assert body["report"] == (job.result or {})["report"]

    document = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report.pdf", headers=owner.headers
    )
    assert document.status_code == 200, document.text
    assert document.headers["content-type"] == "application/pdf"
    assert document.headers["cache-control"] == "private, no-store"
    assert f'sova-integrity-{version.id}.pdf' in document.headers["content-disposition"]
    assert document.content.startswith(b"%PDF-1.4")
    assert str(version.id).encode() in document.content
    assert str(job.id).encode() in document.content

    failed = jobs.enqueue(
        db_session,
        workspace_id=owner.workspace.id,
        job_type="export",
        input={"version_id": str(version.id), "format": "glb", "printable": False, "game": None},
        created_by=owner.user.id,
        project_id=version.project_id,
        project_version_id=version.id,
    )
    failed.status = JobStatus.running
    db_session.flush()
    failed_report = {**(job.result or {})["report"], "summary": "latest failed integrity gate"}
    jobs.fail(
        db_session,
        failed,
        code="export_blocked",
        message="latest failed integrity gate",
        retryable=False,
        details={"report": failed_report},
    )
    assert job.finished_at is not None
    failed.finished_at = job.finished_at + timedelta(seconds=1)
    db_session.flush()
    restored_failure = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report", headers=owner.headers
    )
    assert restored_failure.status_code == 200
    assert restored_failure.json()["job_id"] == str(failed.id)
    assert restored_failure.json()["report"] == failed_report

    unrelated = jobs.enqueue(
        db_session,
        workspace_id=owner.workspace.id,
        job_type="export",
        input={"version_id": str(version.id), "format": "stl", "printable": False, "game": None},
        created_by=owner.user.id,
        project_id=version.project_id,
        project_version_id=version.id,
    )
    unrelated.status = JobStatus.running
    db_session.flush()
    jobs.succeed(
        db_session,
        unrelated,
        {"report": {"status": "fail", "summary": "wrong export"}},
    )
    still_glb = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report", headers=owner.headers
    )
    assert still_glb.status_code == 200
    assert still_glb.json()["job_id"] == str(failed.id)

    hidden = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report", headers=stranger.headers
    )
    assert hidden.status_code == 404
    hidden_pdf = api_client.get(
        f"/api/v1/models/{version.id}/integrity-report.pdf", headers=stranger.headers
    )
    assert hidden_pdf.status_code == 404


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


def test_commercial_export_rejects_non_commercial_lineage_before_enqueue(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    project.license_id = "CC-BY-NC-4.0"
    db_session.flush()

    refused = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "stl", "commercial": True},
        headers=actor.headers,
    )
    assert refused.status_code == 422
    assert "commercial export is forbidden" in refused.json()["error"]["message"]
    assert db_session.query(Job).filter_by(project_version_id=version.id).count() == 0

    allowed = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "stl", "commercial": False},
        headers=actor.headers,
    )
    assert allowed.status_code == 202, allowed.text


def test_a_game_ready_export_carries_lods_uvs_and_a_collider(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    for refused in (
        {"format": "stl", "game": {}},
        {"format": "glb", "printable": True, "game": {}},
    ):
        response = api_client.post(
            f"/api/v1/models/{version.id}/exports", json=refused, headers=actor.headers
        )
        assert response.status_code == 422, refused
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "glb", "game": {"name": "Crate", "lod_ratios": [0.5]}},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["report"]
    assert [lod["name"] for lod in report["lods"]] == ["Crate_LOD0", "Crate_LOD1"]
    collider = report["collider"]
    assert collider["name"] == "UCX_Crate_00" and report["uv"] is True
    assert collider["triangles"] <= collider["triangle_limit"] == 255
    assert collider["is_convex"] is True and collider["is_watertight"] is True
    assert collider["volume_ratio_pct"] is not None
    assert isinstance(collider["floor_offset_mm"], float)
    assert report["size_m"] == pytest.approx([0.02, 0.005, 0.01])  # Y is up in an engine
    export_asset = db_session.get(Asset, uuid.UUID((job.result or {})["asset_id"]))
    assert export_asset is not None and export_asset.format == "glb"
    assert export_asset.metadata_["game_ready"] is True
    cleanup_keys.append(export_asset.storage_key)
