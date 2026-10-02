"""Self-learning plan step 1: training consent is off by default, owner-only, versioned."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import WorkspaceRole
from app.models.training_consent import ProjectTrainingConsentEvent
from tests.integration.conftest import Actor, make_actor


def _create_project(api_client: TestClient, actor: Actor, name: str = "Scan") -> str:
    response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": name},
        headers=actor.headers,
    )
    return str(response.json()["id"])


def test_consent_defaults_off_and_is_owner_only(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor)
    path = f"/api/v1/projects/{project_id}/training-consent"

    # off by default, no history yet
    default = api_client.get(path, headers=actor.headers)
    assert default.status_code == 200, default.text
    assert default.json() == {
        "project_id": project_id,
        "enabled": False,
        "updated_by": None,
        "updated_at": None,
    }
    assert api_client.get(f"{path}/history", headers=actor.headers).json() == []

    # the owner grants it
    granted = api_client.put(path, json={"enabled": True}, headers=actor.headers)
    assert granted.status_code == 200, granted.text
    body = granted.json()
    assert body["enabled"] is True
    assert body["updated_by"] == str(actor.user.id)
    assert body["updated_at"]

    history = api_client.get(f"{path}/history", headers=actor.headers).json()
    assert len(history) == 1
    assert history[0]["action"] == "granted"
    assert history[0]["changed_by"] == str(actor.user.id)

    # reading back shows the granted state
    assert api_client.get(path, headers=actor.headers).json()["enabled"] is True

    # the owner revokes it — the snapshot flips, a second history event is appended
    revoked = api_client.put(path, json={"enabled": False}, headers=actor.headers)
    assert revoked.status_code == 200
    assert revoked.json()["enabled"] is False

    # both toggles are recorded — a real event log, not an overwritten single row.
    # (ties on `created_at` aren't resolved to a guaranteed order here, same as the
    # existing `created_at.desc()` listings elsewhere in the API, e.g. ai_commands.py)
    history_after_revoke = api_client.get(f"{path}/history", headers=actor.headers).json()
    assert sorted(h["action"] for h in history_after_revoke) == ["granted", "revoked"]

    # exactly one event per toggle, ever — never rewritten
    assert db_session.query(ProjectTrainingConsentEvent).count() == 2

    # an editor in the same workspace may see the state but not change it
    editor = make_actor(db_session, role=WorkspaceRole.editor, workspace=actor.workspace)
    assert api_client.get(path, headers=editor.headers).status_code == 200
    denied = api_client.put(path, json={"enabled": True}, headers=editor.headers)
    assert denied.status_code == 403

    # an admin — one rank below owner — is denied too; this is an ownership decision
    admin = make_actor(db_session, role=WorkspaceRole.admin, workspace=actor.workspace)
    assert api_client.put(path, json={"enabled": True}, headers=admin.headers).status_code == 403

    # a stranger with no membership gets 404, not 403 — the project is invisible to them
    foreign = make_actor(db_session)
    assert api_client.get(path, headers=foreign.headers).status_code == 404
    assert api_client.put(path, json={"enabled": True}, headers=foreign.headers).status_code == 404

    # consent did not move after all the denied attempts
    assert api_client.get(path, headers=actor.headers).json()["enabled"] is False


def test_consent_is_per_project(api_client: TestClient, actor: Actor) -> None:
    project_a = _create_project(api_client, actor, "A")
    project_b = _create_project(api_client, actor, "B")

    api_client.put(
        f"/api/v1/projects/{project_a}/training-consent",
        json={"enabled": True},
        headers=actor.headers,
    )

    assert (
        api_client.get(
            f"/api/v1/projects/{project_a}/training-consent", headers=actor.headers
        ).json()["enabled"]
        is True
    )
    assert (
        api_client.get(
            f"/api/v1/projects/{project_b}/training-consent", headers=actor.headers
        ).json()["enabled"]
        is False
    )
