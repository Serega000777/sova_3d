"""T-055/T-038: the numeric inspector edits a version through the same kernel path as AI."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import geometry as kernel

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Operation, ProjectVersion
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import (  # reuse the fake kernel + helpers
    cleanup_keys,  # noqa: F401
    command,
    kernel_or_fake,  # noqa: F401
    new_project,
    run_all,
)


def build_box(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> tuple[str, str]:
    """Returns (project_id, version_id) for a plain box built by the stub planner."""
    project_id = new_project(api_client, actor)
    response = command(api_client, actor, project_id, "Box 40x20x8 mm")
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return project_id, str((job.result or {})["version_id"])


def edit(
    api_client: TestClient,
    actor: Actor,
    version_id: str,
    *,
    operations: list[dict[str, Any]],
    **b: Any,
) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={"operations": operations, **b},
        headers=actor.headers,
    )


def body_name(db_session: Session, version_id: str) -> str:
    version = db_session.get(ProjectVersion, version_id)
    assert version is not None
    bodies = (version.provenance or {})["bodies"]
    return str(bodies[-1]["name"])


def test_dimension_edit_creates_a_child_version_with_the_full_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    target = body_name(db_session, version_id)

    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": target, "width_mm": 60, "height_mm": 12}],
        label="Resize to 60 × 20 × 12 mm",
    )
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "manual_edit"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["source_version_id"] == version_id

    child = db_session.get(ProjectVersion, result["version_id"])
    assert child is not None
    assert str(child.parent_version_id) == version_id
    assert child.label == "Resize to 60 × 20 × 12 mm"
    assert child.provenance["operation"] == "manual_edit"

    # The child owns the replayed history plus the edit — the next edit can build on it.
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [op.operation_type for op in logged] == ["create_box", "set_dimensions"]
    assert logged[-1].params["width_mm"] == 60
    assert logged[-1].entity_refs == [target]

    if kernel.available():  # the real kernel actually rescales the body
        size = result["bodies"][-1]["bbox_mm"]["size"]
        assert (round(size[0]), round(size[2])) == (60, 12)


def test_edit_naming_an_unknown_body_is_rejected_before_the_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": "nope", "width_mm": 10}],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert run_all(db_session, storage) == []


def test_edit_of_an_uploaded_model_without_history_is_rejected(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "manual"},
        headers=actor.headers,
    ).json()["id"]
    version_id: str = api_client.post(
        f"/api/v1/projects/{project_id}/versions", json={}, headers=actor.headers
    ).json()["id"]

    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": "body", "width_mm": 10}],
    )
    assert response.status_code == 422
    assert "parametric history" in response.json()["error"]["message"]


def test_edit_requires_workspace_membership(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    from tests.integration.conftest import make_actor

    _, version_id = build_box(api_client, actor, db_session, storage)
    stranger = make_actor(db_session)
    response = edit(
        api_client,
        stranger,
        version_id,
        operations=[{"type": "set_dimensions", "target": "body", "width_mm": 10}],
    )
    assert response.status_code == 404
