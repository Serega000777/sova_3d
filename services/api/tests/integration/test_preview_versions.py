"""T-052: a change can be previewed — built, looked at, then accepted or thrown away."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Project, ProjectVersion
from app.models.execution import JobStatus
from app.models.versioning import VersionState
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import (  # reuse the fake kernel + helpers
    cleanup_keys,  # noqa: F401
    command,
    kernel_or_fake,  # noqa: F401
    new_project,
    run_all,
)


def build(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, **extra: Any
) -> tuple[str, str]:
    """A project with one accepted version; returns (project_id, version_id)."""
    project_id = new_project(api_client, actor)
    response = command(api_client, actor, project_id, "Box 40x20x8 mm", **extra)
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return project_id, str((job.result or {})["version_id"])


def test_a_preview_is_built_but_does_not_become_the_project(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, accepted_id = build(api_client, actor, db_session, storage)

    response = command(
        api_client,
        actor,
        project_id,
        "Box 90x20x8 mm",
        project_version_id=accepted_id,
        preview=True,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["preview"] is True

    draft = db_session.get(ProjectVersion, result["version_id"])
    assert draft is not None and draft.state is VersionState.draft
    project = db_session.get(Project, project_id)
    assert project is not None
    assert str(project.head_version_id) == accepted_id  # the project has not moved


def test_the_comparison_says_what_would_change(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, accepted_id = build(api_client, actor, db_session, storage)
    response = api_client.post(
        f"/api/v1/models/{accepted_id}/edits",
        json={
            "operations": [{"type": "set_dimensions", "target": "body", "width_mm": 90}],
            "preview": True,
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    draft_id = (job.result or {})["version_id"]

    comparison = api_client.get(
        f"/api/v1/versions/{draft_id}/compare", headers=actor.headers
    ).json()
    assert comparison["awaiting_decision"] is True
    assert comparison["before"]["version_id"] == accepted_id
    assert comparison["before"]["state"] == "finalized"
    assert comparison["after"]["state"] == "draft"
    assert comparison["edit_operations"][0]["type"] == "set_dimensions"


def test_accepting_a_preview_makes_it_the_project_head(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, accepted_id = build(api_client, actor, db_session, storage)
    command(
        api_client,
        actor,
        project_id,
        "Box 90x20x8 mm",
        project_version_id=accepted_id,
        preview=True,
    )
    (job,) = run_all(db_session, storage)
    draft_id = (job.result or {})["version_id"]

    kept = api_client.post(f"/api/v1/versions/{draft_id}/finalize", headers=actor.headers)
    assert kept.status_code == 200, kept.text
    assert kept.json()["state"] == "finalized"

    project = db_session.get(Project, project_id)
    assert project is not None
    assert str(project.head_version_id) == draft_id

    # Accepting is final: the version is now history and cannot be thrown away.
    refused = api_client.delete(f"/api/v1/versions/{draft_id}", headers=actor.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "conflict"


def test_rejecting_a_preview_leaves_no_trace(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, accepted_id = build(api_client, actor, db_session, storage)
    command(
        api_client,
        actor,
        project_id,
        "Box 90x20x8 mm",
        project_version_id=accepted_id,
        preview=True,
    )
    (job,) = run_all(db_session, storage)
    draft_id = (job.result or {})["version_id"]

    discarded = api_client.delete(f"/api/v1/versions/{draft_id}", headers=actor.headers)
    assert discarded.status_code == 204

    assert db_session.get(ProjectVersion, draft_id) is None
    project = db_session.get(Project, project_id)
    assert project is not None
    assert str(project.head_version_id) == accepted_id
    remaining = api_client.get(
        f"/api/v1/projects/{project_id}/versions", headers=actor.headers
    ).json()
    assert [v["id"] for v in remaining] == [accepted_id]


def test_without_preview_a_command_still_lands_directly(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    """The default is unchanged: build it and keep it."""
    project_id, version_id = build(api_client, actor, db_session, storage)
    version = db_session.get(ProjectVersion, version_id)
    assert version is not None and version.state is VersionState.finalized
    project = db_session.get(Project, project_id)
    assert project is not None and str(project.head_version_id) == version_id
