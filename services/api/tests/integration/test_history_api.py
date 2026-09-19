"""E18 (F-016): "верни как было" — an earlier state becomes a new version, never a deletion."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import AIRequest, AIRequestStatus, JobStatus, Operation
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def build(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> tuple[str, str]:
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Plate 60x40x8 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    return str(result["version_id"]), str(result["bodies"][-1]["name"])


def edit(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    version_id: str,
    operations: list[dict[str, object]],
    label: str,
) -> str:
    response = api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={"operations": operations, "label": label},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def operation_types(db_session: Session, version_id: str) -> list[str]:
    rows = db_session.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == version_id)
        .order_by(Operation.sequence_no)
    ).all()
    return [row.operation_type for row in rows]


def three_versions(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> tuple[str, str, str]:
    """v1 plate, v2 with a hole, v3 resized — the history a rollback walks."""
    v1, body = build(api_client, actor, db_session, storage, project_id)
    hole = {
        "type": "add_hole",
        "target": body,
        "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
        "position_mm": [10, 10],
        "diameter_mm": 5,
    }
    v2 = edit(api_client, actor, db_session, storage, v1, [hole], "hole")
    resize = {"type": "set_dimensions", "target": body, "width_mm": 80}
    v3 = edit(api_client, actor, db_session, storage, v2, [resize], "resize")
    return v1, v2, v3


def test_going_back_before_the_hole_restores_the_plate_as_a_new_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    v1, v2, v3 = three_versions(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/projects/{project}/rollback",
        json={"expression": "верни как было до отверстия"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    restored = response.json()
    assert restored["sequence_no"] == 4  # nothing was deleted: it is a new version
    assert restored["parent_version_id"] == v3  # on top of the head
    assert restored["label"].startswith("Back to v1")
    assert restored["provenance"]["restored_version_id"] == v1
    assert "before" in restored["provenance"]["how"]
    # the same content as v1: assets and operation log
    v1_assets = {
        a["role"]: a["asset_id"]
        for a in api_client.get(f"/api/v1/versions/{v1}", headers=actor.headers).json()["assets"]
    }
    assert {a["role"]: a["asset_id"] for a in restored["assets"]} == v1_assets
    assert (
        operation_types(db_session, restored["id"])
        == operation_types(db_session, v1)
        == ["create_box"]
    )
    # and it is the head now
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["head_version"]["id"] == restored["id"]
    # v2 is untouched
    assert operation_types(db_session, v2) == ["create_box", "add_hole"]


def test_a_version_number_and_a_step_count_both_work(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    v1, v2, v3 = three_versions(api_client, actor, db_session, storage, project)
    back_to_v2 = api_client.post(
        f"/api/v1/projects/{project}/rollback",
        json={"expression": "go back to v2"},
        headers=actor.headers,
    ).json()
    assert back_to_v2["provenance"]["restored_version_id"] == v2
    assert operation_types(db_session, back_to_v2["id"]) == ["create_box", "add_hole"]

    # "undo" from here steps over the rollback itself back to v3
    undo = api_client.post(
        f"/api/v1/projects/{project}/rollback",
        json={"expression": "undo"},
        headers=actor.headers,
    ).json()
    assert undo["provenance"]["restored_version_id"] == v3
    assert undo["provenance"]["how"] == "1 change(s) back"


def test_nothing_that_far_back_is_an_honest_422(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    three_versions(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/projects/{project}/rollback",
        json={"expression": "верни как было неделю назад"},
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert "that far back" in response.json()["error"]["message"]
    response = api_client.post(
        f"/api/v1/projects/{project}/rollback",
        json={"expression": "back to v3"},
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert "already the current" in response.json()["error"]["message"]


def test_typing_the_sentence_as_a_command_runs_a_rollback_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    v1, v2, v3 = three_versions(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Верни как было до отверстия", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    queued = api_client.get(f"/api/v1/jobs/{accepted['job_id']}", headers=actor.headers).json()
    assert queued["type"] == "rollback"  # no planner, no kernel
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["restored_version_id"] == v1 and result["status"] == "executed"
    request = db_session.get(AIRequest, accepted["ai_request_id"])
    assert request is not None and request.status is AIRequestStatus.executed
    assert str(request.result_version_id) == result["version_id"]
    assert operation_types(db_session, result["version_id"]) == ["create_box"]
