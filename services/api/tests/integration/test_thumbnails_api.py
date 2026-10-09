"""Canonical project/version thumbnails: authorized job, PNG artifact, library pointer."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Asset, ProjectVersion
from app.models.core import WorkspaceRole
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import box_bytes, project, run_all, upload  # noqa: F401


def test_thumbnail_job_attaches_png_and_library_exposes_head_pointer(
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
        f"/api/v1/versions/{version_id}/thumbnail", headers=actor.headers
    )
    assert queued.status_code == 202, queued.text
    (rendered,) = run_all(db_session, storage)
    assert rendered.status is JobStatus.succeeded, rendered.error
    thumbnail_id = str((rendered.result or {})["asset_id"])

    version = db_session.get(ProjectVersion, version_id)
    assert version is not None
    links = {link.role: str(link.asset_id) for link in version.assets}
    assert links[AssetRole.thumbnail] == thumbnail_id
    thumbnail = db_session.get(Asset, thumbnail_id)
    assert thumbnail is not None and thumbnail.mime == "image/png"
    assert storage.get(thumbnail.storage_key).startswith(b"\x89PNG\r\n\x1a\n")

    listed = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["thumbnail_asset_id"] == thumbnail_id

    # Idempotency is derived from immutable version + source, so a retry does not create work.
    repeated = api_client.post(
        f"/api/v1/versions/{version_id}/thumbnail", headers=actor.headers
    )
    assert repeated.json()["job_id"] == queued.json()["job_id"]
    assert run_all(db_session, storage) == []


def test_thumbnail_generation_requires_editor_and_hides_foreign_versions(
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

    assert (
        api_client.post(
            f"/api/v1/versions/{version['id']}/thumbnail", headers=viewer.headers
        ).status_code
        == 403
    )
    assert (
        api_client.post(
            f"/api/v1/versions/{version['id']}/thumbnail", headers=stranger.headers
        ).status_code
        == 404
    )
