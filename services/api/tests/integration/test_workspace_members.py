import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, WorkspaceMember
from app.models.core import WorkspaceKind, WorkspaceRole
from tests.integration.conftest import Actor, make_actor


def test_user_creates_team_workspace_and_becomes_owner(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    created = api_client.post(
        "/api/v1/workspaces",
        json={"name": "  Studio North  "},
        headers=actor.headers,
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Studio North"
    assert created.json()["kind"] == "team"
    assert created.json()["role"] == "owner"

    workspace_id = uuid.UUID(created.json()["id"])
    membership = db_session.get(WorkspaceMember, (workspace_id, actor.user.id))
    assert membership is not None and membership.role is WorkspaceRole.owner

    me = api_client.get("/api/v1/auth/me", headers=actor.headers)
    assert me.status_code == 200
    assert any(row["id"] == str(workspace_id) for row in me.json()["workspaces"])

    blank = api_client.post("/api/v1/workspaces", json={"name": "   "}, headers=actor.headers)
    assert blank.status_code == 422


def test_owner_manages_registered_team_members_fail_closed(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    actor.workspace.kind = WorkspaceKind.team
    invited = User(email="member@example.com", display_name="Member")
    db_session.add(invited)
    db_session.flush()
    url = f"/api/v1/workspaces/{actor.workspace.id}/members"

    added = api_client.post(
        url,
        json={"email": " MEMBER@example.com ", "role": "viewer"},
        headers=actor.headers,
    )
    assert added.status_code == 201
    assert added.json()["user_id"] == str(invited.id)
    assert added.json()["role"] == "viewer"

    listed = api_client.get(url, headers=actor.headers)
    assert listed.status_code == 200
    assert [(row["email"], row["role"]) for row in listed.json()] == [
        (actor.user.email, "owner"),
        ("member@example.com", "viewer"),
    ]

    changed = api_client.patch(
        f"{url}/{invited.id}", json={"role": "editor"}, headers=actor.headers
    )
    assert changed.status_code == 200 and changed.json()["role"] == "editor"

    duplicate = api_client.post(
        url, json={"email": invited.email, "role": "admin"}, headers=actor.headers
    )
    assert duplicate.status_code == 409
    unknown = api_client.post(
        url, json={"email": "nobody@example.com", "role": "viewer"}, headers=actor.headers
    )
    assert unknown.status_code == 404

    owner_change = api_client.patch(
        f"{url}/{actor.user.id}", json={"role": "viewer"}, headers=actor.headers
    )
    assert owner_change.status_code == 422

    removed = api_client.delete(f"{url}/{invited.id}", headers=actor.headers)
    assert removed.status_code == 204
    assert db_session.get(WorkspaceMember, (actor.workspace.id, invited.id)) is None


def test_workspace_member_management_requires_team_owner(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    personal = api_client.get(
        f"/api/v1/workspaces/{actor.workspace.id}/members", headers=actor.headers
    )
    assert personal.status_code == 422

    actor.workspace.kind = WorkspaceKind.team
    editor = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.editor)
    visible = api_client.get(
        f"/api/v1/workspaces/{actor.workspace.id}/members", headers=editor.headers
    )
    assert visible.status_code == 200
    assert {row["role"] for row in visible.json()} == {"owner", "editor"}

    forbidden = api_client.post(
        f"/api/v1/workspaces/{actor.workspace.id}/members",
        json={"email": "nobody@example.com", "role": "viewer"},
        headers=editor.headers,
    )
    assert forbidden.status_code == 403

    stranger = make_actor(db_session)
    hidden = api_client.get(
        f"/api/v1/workspaces/{actor.workspace.id}/members", headers=stranger.headers
    )
    assert hidden.status_code == 404

    missing = api_client.delete(
        f"/api/v1/workspaces/{actor.workspace.id}/members/{uuid.uuid4()}", headers=actor.headers
    )
    assert missing.status_code == 404
