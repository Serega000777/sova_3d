from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import blender_handoff, exporters

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


def _fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    def export_mesh(
        _source: Path, _source_format: str, _target: str, output: Path, **_kwargs: Any
    ) -> exporters.ExportOutcome:
        output.write_bytes(b"glTF" + b"\0" * 64)
        return exporters.ExportOutcome(ok=True, output_path=str(output))

    def package(source: Path, output: Path) -> blender_handoff.BlenderHandoffOutcome:
        output.write_bytes(b"BLENDER-v300" + b"\0" * 64)
        script = Path(blender_handoff.__file__).with_name("blender_handoff_script.py")
        return blender_handoff.BlenderHandoffOutcome(
            ok=True,
            report=blender_handoff.BlenderHandoffReport(
                schema_version=1,
                operation="editable_scene",
                blender_version="4.3.3",
                objects=1,
                meshes=1,
                materials=0,
                vertices=8,
                triangles=12,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                min_bounds_m=[-0.01, -0.01, -0.01],
                max_bounds_m=[0.01, 0.01, 0.01],
                external_refs=[],
                scripts=[],
                drivers=[],
                packed=True,
                sandbox_network_interfaces=["lo"],
                sandbox_uid=65534,
                capability_effective="0000000000000000",
                capability_permitted="0000000000000000",
                capability_ambient="0000000000000000",
                no_new_privileges=True,
            ),
        )

    monkeypatch.setattr("app.jobs.blender_handoff.exporters.export_mesh", export_mesh)
    monkeypatch.setattr("app.jobs.blender_handoff.blender_handoff.package_editable_scene", package)


def test_finalized_model_creates_downloadable_blend_export(
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
        f"/api/v1/models/{version.id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers={**actor.headers, "Idempotency-Key": "blend-1"},
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    assert result["format"] == "blend" and result["operation"] == "editable_scene"
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None and made.format == "blend" and made.mime == "application/x-blender"
    cleanup_keys.append(made.storage_key)
    assert storage.get(made.storage_key).startswith(b"BLENDER")
    assert db_session.get(VersionAsset, (version.id, made.id, AssetRole.export)) is not None

    download = api_client.get(f"/api/v1/assets/{made.id}/download", headers=actor.headers)
    assert download.status_code == 200
    assert download.json()["format"] == "blend"
    assert download.json()["byte_size"] == made.byte_size


def test_handoff_requires_editor_finalized_version_and_strict_body(
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
        f"/api/v1/models/{draft_version.id}/blender-handoffs", json={}, headers=actor.headers
    )
    assert draft.status_code == 422
    extra = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs",
        json={"python": "print('unsafe')"},
        headers=actor.headers,
    )
    assert extra.status_code == 422

    stranger = make_actor(db_session)
    foreign = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=stranger.headers
    )
    assert foreign.status_code == 404


def test_handoff_idempotency_reuses_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    headers = {**actor.headers, "Idempotency-Key": "same-blend"}
    first = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=headers
    )
    second = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=headers
    )
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
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=actor.headers
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

    monkeypatch.setattr(
        "app.jobs.blender_handoff.blender_handoff.package_editable_scene", forbidden
    )
    runner.run_once(db_session, storage, commit=db_session.flush)
    db_session.refresh(job)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "lineage_invalid"
    assert launched is False
