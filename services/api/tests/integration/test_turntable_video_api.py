"""Immutable 3D version -> sandboxed turntable MP4 job and downloadable asset."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers render_turntable_video
from app.models import Asset
from app.models.core import WorkspaceRole
from app.models.execution import JobArtifact, JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import box_bytes, project, run_all, upload  # noqa: F401


def test_turntable_video_job_creates_real_version_scoped_mp4(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source = upload(api_client, actor, box_bytes("stl"), "box.stl", "model/stl")
    accepted = api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": source},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (imported,) = run_all(db_session, storage)
    assert imported.status is JobStatus.succeeded, imported.error
    version_id = str((imported.result or {})["version_id"])

    queued = api_client.post(
        f"/api/v1/versions/{version_id}/turntable-video",
        headers=actor.headers,
    )
    assert queued.status_code == 202, queued.text
    (rendered,) = run_all(db_session, storage)
    assert rendered.status is JobStatus.succeeded, rendered.error
    result = rendered.result or {}
    assert result["version_id"] == version_id
    assert result["metadata"] == {
        "width": 480,
        "height": 320,
        "fps": 12,
        "frame_count": 12,
        "duration_seconds": 1.0,
        "render_kind": "deterministic_turntable",
    }

    video_id = uuid.UUID(str(result["asset_id"]))
    video = db_session.get(Asset, video_id)
    assert video is not None
    assert video.format == "mp4" and video.mime == "video/mp4"
    assert storage.get(video.storage_key)[4:8] == b"ftyp"
    artifact = db_session.get(
        JobArtifact,
        {"job_id": rendered.id, "asset_id": video_id, "role": "turntable_video"},
    )
    assert artifact is not None

    download = api_client.get(f"/api/v1/assets/{video_id}/download", headers=actor.headers)
    assert download.status_code == 200, download.text

    repeated = api_client.post(
        f"/api/v1/versions/{version_id}/turntable-video",
        headers=actor.headers,
    )
    assert repeated.json()["job_id"] == queued.json()["job_id"]
    assert run_all(db_session, storage) == []


def test_turntable_video_requires_editor_and_hides_foreign_versions(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    source = upload(api_client, actor, box_bytes("stl"), "box.stl", "model/stl")
    version = api_client.post(
        f"/api/v1/projects/{project}/versions",
        json={"assets": {"model": source}},
        headers=actor.headers,
    ).json()
    viewer = make_actor(db_session, WorkspaceRole.viewer, actor.workspace)
    stranger = make_actor(db_session)

    endpoint = f"/api/v1/versions/{version['id']}/turntable-video"
    assert api_client.post(endpoint, headers=viewer.headers).status_code == 403
    assert api_client.post(endpoint, headers=stranger.headers).status_code == 404
