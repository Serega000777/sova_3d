"""E30 (F-078): a parametric version exports as STEP/IGES; a mesh version cannot."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.models.versioning import Asset
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import box_bytes, project, run_all, upload  # noqa: F401


def test_a_built_version_exports_as_step_and_iges(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    from worker import geometry as kernel

    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Box 40x20x8 mm with a 5 mm hole", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    version_id = str((built.result or {})["version_id"])

    for fmt, magic in (("step", b"ISO-10303-21"), ("iges", None)):
        accepted = api_client.post(
            f"/api/v1/models/{version_id}/exports", json={"format": fmt}, headers=actor.headers
        )
        assert accepted.status_code == 202, accepted.text
        (job,) = run_all(db_session, storage)
        if not kernel.available():
            # the fake kernel wrote a fake B-Rep: the real writer is the only one that can go on
            assert job.status is JobStatus.failed
            continue
        assert job.status is JobStatus.succeeded, job.error
        result = job.result or {}
        assert result["format"] == fmt and result["byte_size"] > 0
        assert result["report"]["bodies"][0]["volume_mm3"] > 0
        download = api_client.get(
            f"/api/v1/assets/{result['asset_id']}/download", headers=actor.headers
        )
        assert download.status_code == 200, download.text
        assert download.json()["format"] == fmt
        if magic:
            stored = db_session.get(Asset, uuid.UUID(result["asset_id"]))
            assert stored is not None
            assert storage.get(stored.storage_key).startswith(magic)


def test_a_mesh_version_has_no_brep_to_export(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    asset_id = upload(api_client, actor, box_bytes("stl"), "box.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{project}/imports", json={"asset_id": asset_id}, headers=actor.headers
    )
    (job,) = run_all(db_session, storage)
    version_id = str((job.result or {})["version_id"])
    refused = api_client.post(
        f"/api/v1/models/{version_id}/exports", json={"format": "step"}, headers=actor.headers
    )
    assert refused.status_code == 422
    assert "B-Rep" in refused.json()["error"]["message"]
    # the mesh formats still work for it
    accepted = api_client.post(
        f"/api/v1/models/{version_id}/exports", json={"format": "glb"}, headers=actor.headers
    )
    assert accepted.status_code == 202
