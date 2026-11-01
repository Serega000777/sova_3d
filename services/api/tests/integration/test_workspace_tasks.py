import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import WorkspaceKind, WorkspaceRole
from tests.integration.conftest import Actor, make_actor


def test_team_tasks_have_exact_open_count_and_revision_guard(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    actor.workspace.kind = WorkspaceKind.team
    url = f"/api/v1/workspaces/{actor.workspace.id}/tasks"

    first = api_client.post(
        url, json={"title": "  Check balcony clearances  "}, headers=actor.headers
    )
    assert first.status_code == 201, first.text
    assert first.json()["title"] == "Check balcony clearances"
    assert first.json()["completed"] is False
    assert first.json()["revision"] == 0

    second = api_client.post(url, json={"title": "Prepare render"}, headers=actor.headers)
    assert second.status_code == 201, second.text
    listed = api_client.get(url, headers=actor.headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["open_count"] == 2
    assert listed.json()["total_count"] == 2
    assert {task["title"] for task in listed.json()["tasks"]} == {
        "Check balcony clearances",
        "Prepare render",
    }

    task_id = first.json()["id"]
    done = api_client.patch(
        f"{url}/{task_id}",
        json={"expected_revision": 0, "completed": True},
        headers=actor.headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["completed"] is True
    assert done.json()["completed_at"] is not None
    assert done.json()["revision"] == 1
    after = api_client.get(url, headers=actor.headers).json()
    assert after["open_count"] == 1 and after["total_count"] == 2

    stale = api_client.patch(
        f"{url}/{task_id}",
        json={"expected_revision": 0, "completed": False},
        headers=actor.headers,
    )
    assert stale.status_code == 409


def test_task_roles_and_workspace_boundaries_fail_closed(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    personal_url = f"/api/v1/workspaces/{actor.workspace.id}/tasks"
    assert api_client.get(personal_url, headers=actor.headers).status_code == 422

    actor.workspace.kind = WorkspaceKind.team
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    editor = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.editor)
    created = api_client.post(
        personal_url,
        json={"title": "Inspect model"},
        headers=editor.headers,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert api_client.get(personal_url, headers=viewer.headers).status_code == 200
    assert (
        api_client.post(personal_url, json={"title": "No"}, headers=viewer.headers).status_code
        == 403
    )
    assert (
        api_client.patch(
            f"{personal_url}/{task_id}",
            json={"expected_revision": 0, "completed": True},
            headers=viewer.headers,
        ).status_code
        == 403
    )

    stranger = make_actor(db_session)
    assert api_client.get(personal_url, headers=stranger.headers).status_code == 404
    stranger.workspace.kind = WorkspaceKind.team
    wrong_workspace = f"/api/v1/workspaces/{stranger.workspace.id}/tasks/{task_id}"
    assert (
        api_client.patch(
            wrong_workspace,
            json={"expected_revision": 0, "completed": True},
            headers=stranger.headers,
        ).status_code
        == 404
    )
    missing = api_client.patch(
        f"{personal_url}/{uuid.uuid4()}",
        json={"expected_revision": 0, "completed": True},
        headers=editor.headers,
    )
    assert missing.status_code == 404


def test_task_payloads_reject_blank_or_noop_updates(api_client: TestClient, actor: Actor) -> None:
    actor.workspace.kind = WorkspaceKind.team
    url = f"/api/v1/workspaces/{actor.workspace.id}/tasks"
    blank = api_client.post(url, json={"title": "   "}, headers=actor.headers)
    assert blank.status_code == 422
    created = api_client.post(url, json={"title": "Review"}, headers=actor.headers)
    assert created.status_code == 201
    noop = api_client.patch(
        f"{url}/{created.json()['id']}",
        json={"expected_revision": 0},
        headers=actor.headers,
    )
    assert noop.status_code == 422
