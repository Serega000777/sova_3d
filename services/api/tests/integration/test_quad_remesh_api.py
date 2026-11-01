from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import exporters, quad_remesh

import app.jobs.handlers  # noqa: F401
from app.jobs import runner
from app.models import Asset, Job, VersionAsset
from app.models.execution import JobStatus
from app.models.versioning import AssetRole, VersionState
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_exports_api import box_stl
from tests.integration.test_printing_api import seed_version


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def _object_report(name: str, faces: int) -> quad_remesh.QuadRemeshObjectReport:
    return quad_remesh.QuadRemeshObjectReport(
        name=name,
        faces=faces,
        quad_faces=faces - 50,
        triangle_faces=50,
        other_faces=0,
        vertices=faces + 10,
        quad_ratio=round((faces - 50) / faces, 4),
        source_uv_layers=1,
        uv_layers=1,
        uv_coordinates=faces * 4,
        uv_bounds=[0.0, 0.0, 1.0, 1.0],
        uv_transfer="active_surface_projected",
    )


def _fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    object_names: list[str] | None = None,
) -> None:
    def export_mesh(
        _source: Path, _source_format: str, _target: str, output: Path, **_kwargs: Any
    ) -> exporters.ExportOutcome:
        output.write_bytes(b"glTF" + b"\0" * 64)
        return exporters.ExportOutcome(ok=True, output_path=str(output))

    def export_scene(
        inputs: list[exporters.SceneMeshInput], target: str, output: Path, **_kwargs: Any
    ) -> exporters.ExportOutcome:
        assert target == "glb"
        output.write_bytes(b"glTF" + b"\0" * 64)
        return exporters.ExportOutcome(ok=True, output_path=str(output))

    def remesh(source: Path, output: Path, faces: int) -> quad_remesh.QuadRemeshOutcome:
        output.write_bytes(b"Kaydara FBX Binary" + b"\0" * 64)
        script = Path(quad_remesh.__file__).with_name("quad_remesh_script.py")
        names = object_names or ["Part"]
        per_object = [_object_report(name, faces - 20) for name in names]
        return quad_remesh.QuadRemeshOutcome(
            ok=True,
            report=quad_remesh.QuadRemeshReport(
                schema_version=3,
                operation="quad_remesh",
                blender_version="4.3.3",
                target_faces=faces,
                objects=len(per_object),
                faces=sum(entry.faces for entry in per_object),
                quad_faces=sum(entry.quad_faces for entry in per_object),
                triangle_faces=sum(entry.triangle_faces for entry in per_object),
                other_faces=sum(entry.other_faces for entry in per_object),
                vertices=sum(entry.vertices for entry in per_object),
                quad_ratio=round(
                    sum(entry.quad_faces for entry in per_object)
                    / sum(entry.faces for entry in per_object),
                    4,
                ),
                per_object=per_object,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                sandbox_network_interfaces=["lo"],
                sandbox_uid=65534,
                capability_effective="0000000000000000",
                capability_permitted="0000000000000000",
                capability_ambient="0000000000000000",
                no_new_privileges=True,
            ),
        )

    monkeypatch.setattr("app.jobs.quad_remesh.exporters.export_mesh", export_mesh)
    monkeypatch.setattr("app.jobs.quad_remesh.exporters.export_scene", export_scene)
    monkeypatch.setattr("app.jobs.quad_remesh.quad_remesh.remesh_quads", remesh)


def test_finalized_model_creates_downloadable_fbx_export(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    _fake_pipeline(monkeypatch)

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/quad-remeshes",
        json={"target_faces": 4000},
        headers={**actor.headers, "Idempotency-Key": "quad-1"},
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    assert result["format"] == "fbx" and result["target_faces"] == 4000
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None and made.format == "fbx"
    cleanup_keys.append(made.storage_key)
    assert storage.get(made.storage_key).startswith(b"Kaydara")
    assert db_session.get(VersionAsset, (version.id, made.id, AssetRole.export)) is not None

    download = api_client.get(f"/api/v1/assets/{made.id}/download", headers=actor.headers)
    assert download.status_code == 200
    assert download.json()["format"] == "fbx"


def test_quad_remesh_requires_editor_finalized_version_and_strict_body(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    draft_version = projects.create_version_internal(
        db_session,
        project_id=project.id,
        parent_version_id=version.id,
        label="Draft",
        provenance={"operation": "test_draft"},
        assets={AssetRole.model: source.id},
        finalize=False,
        created_by=actor.user.id,
    )
    assert draft_version.state is VersionState.draft
    draft = api_client.post(
        f"/api/v1/models/{draft_version.id}/quad-remeshes", json={}, headers=actor.headers
    )
    assert draft.status_code == 422

    extra = api_client.post(
        f"/api/v1/models/{version.id}/quad-remeshes",
        json={"target_faces": 4000, "python": "print('unsafe')"},
        headers=actor.headers,
    )
    assert extra.status_code == 422

    out_of_bounds = api_client.post(
        f"/api/v1/models/{version.id}/quad-remeshes",
        json={"target_faces": 1_000_000},
        headers=actor.headers,
    )
    assert out_of_bounds.status_code == 422

    stranger = make_actor(db_session)
    foreign = api_client.post(
        f"/api/v1/models/{version.id}/quad-remeshes", json={}, headers=stranger.headers
    )
    assert foreign.status_code == 404

    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "asset_id": str(source.id),
                    "visible": False,
                }
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    scene_empty_rejected = api_client.post(
        f"/api/v1/models/{scene.json()['version_id']}/quad-remeshes",
        json={},
        headers=actor.headers,
    )
    assert scene_empty_rejected.status_code == 422
    assert "no visible geometry" in scene_empty_rejected.text


def test_multi_object_scene_quad_remesh_preserves_every_visible_object(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    moved = [
        [1.0, 0.0, 0.0, 40.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {"id": "part", "name": "Part", "kind": "object", "asset_id": str(source.id)},
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "part",
                    "transform": moved,
                },
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "instance_of": "part",
                    "visible": False,
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    scene_version_id = scene.json()["version_id"]
    _fake_pipeline(monkeypatch, object_names=["Part", "Copy"])

    accepted = api_client.post(
        f"/api/v1/models/{scene_version_id}/quad-remeshes",
        json={"target_faces": 4000},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    assert result["report"]["objects"] == 2
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None
    cleanup_keys.append(made.storage_key)


def test_quad_remesh_rejects_scene_that_drops_a_visible_object(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {"id": "part", "name": "Part", "kind": "object", "asset_id": str(source.id)},
                {"id": "copy", "name": "Copy", "kind": "object", "instance_of": "part"},
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    _fake_pipeline(monkeypatch, object_names=["Part"])

    accepted = api_client.post(
        f"/api/v1/models/{scene.json()['version_id']}/quad-remeshes",
        json={},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.failed
    assert (job.error or {})["code"] == "scene_structure_mismatch"


def test_quad_remesh_idempotency_reuses_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    headers = {**actor.headers, "Idempotency-Key": "same-quad-remesh"}
    first = api_client.post(f"/api/v1/models/{version.id}/quad-remeshes", json={}, headers=headers)
    second = api_client.post(f"/api/v1/models/{version.id}/quad-remeshes", json={}, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


def test_worker_revalidates_queued_lineage_before_blender(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/quad-remeshes", json={}, headers=actor.headers
    )
    job = db_session.get(Job, uuid.UUID(accepted.json()["job_id"]))
    assert job is not None
    job.project_id = None
    db_session.flush()
    launched = False

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal launched
        launched = True
        raise AssertionError("Blender must not run for invalid lineage")

    monkeypatch.setattr("app.jobs.quad_remesh.quad_remesh.remesh_quads", forbidden)
    runner.run_once(db_session, storage, commit=db_session.flush)
    db_session.refresh(job)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "lineage_invalid"
    assert launched is False
