"""Reference 69: shared revision-guarded progress for exact mechanism guides."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import WorkspaceRole
from tests.integration.conftest import Actor, make_actor


def _project(api_client: TestClient, actor: Actor) -> str:
    response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Assembly"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _version(
    api_client: TestClient,
    actor: Actor,
    project_id: str,
    *,
    kind: str = "hinged_lid",
    finalize: bool = True,
) -> str:
    provenance = {
        f"build_{kind}": {
            "kind": kind,
            "joint": {"type": "revolute" if kind == "hinged_lid" else "prismatic"},
            "parts": {"base": "base", "lid": "lid"},
        }
    }
    response = api_client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"provenance": provenance, "finalize": finalize},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_assembly_guide_progress_syncs_with_acl_and_revision_guard(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    stranger = make_actor(db_session)
    version_id = _version(api_client, actor, _project(api_client, actor))
    route = f"/api/v1/versions/{version_id}/assembly-guide-progress"

    empty = api_client.get(route, headers=viewer.headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "version_id": version_id,
        "guide_kind": "hinged_lid",
        "completed_step_ids": [],
        "revision": 0,
        "updated_at": None,
        "updated_by": None,
    }
    blocked = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": ["inspect-parts"],
            "expected_revision": 0,
        },
        headers=viewer.headers,
    )
    assert blocked.status_code == 403

    saved = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": ["insert-pin", "inspect-parts"],
            "expected_revision": 0,
        },
        headers=actor.headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["completed_step_ids"] == ["inspect-parts", "insert-pin"]
    assert saved.json()["revision"] == 1
    assert saved.json()["updated_by"] == str(actor.user.id)
    assert api_client.get(route, headers=viewer.headers).json() == saved.json()

    stale = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": [],
            "expected_revision": 0,
        },
        headers=actor.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == 1
    invalid = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": ["unknown-step"],
            "expected_revision": 1,
        },
        headers=actor.headers,
    )
    assert invalid.status_code == 422
    wrong_kind = api_client.put(
        route,
        json={
            "guide_kind": "sliding_lid",
            "completed_step_ids": [],
            "expected_revision": 1,
        },
        headers=actor.headers,
    )
    assert wrong_kind.status_code == 422
    duplicate = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": ["inspect-parts", "inspect-parts"],
            "expected_revision": 1,
        },
        headers=actor.headers,
    )
    assert duplicate.status_code == 422

    reset = api_client.put(
        route,
        json={
            "guide_kind": "hinged_lid",
            "completed_step_ids": [],
            "expected_revision": 1,
        },
        headers=actor.headers,
    )
    assert reset.status_code == 200
    assert reset.json()["revision"] == 2
    assert reset.json()["completed_step_ids"] == []
    assert api_client.get(route, headers=stranger.headers).status_code == 404
    assert (
        api_client.put(
            route,
            json={
                "guide_kind": "hinged_lid",
                "completed_step_ids": [],
                "expected_revision": 2,
            },
            headers=stranger.headers,
        ).status_code
        == 404
    )


def test_assembly_guide_progress_rejects_drafts_and_cross_kind_steps(
    api_client: TestClient, actor: Actor
) -> None:
    project_id = _project(api_client, actor)
    draft_id = _version(api_client, actor, project_id, finalize=False)
    draft = api_client.get(
        f"/api/v1/versions/{draft_id}/assembly-guide-progress", headers=actor.headers
    )
    assert draft.status_code == 422

    sliding_id = _version(api_client, actor, project_id, kind="sliding_lid")
    route = f"/api/v1/versions/{sliding_id}/assembly-guide-progress"
    invalid = api_client.put(
        route,
        json={
            "guide_kind": "sliding_lid",
            "completed_step_ids": ["insert-pin"],
            "expected_revision": 0,
        },
        headers=actor.headers,
    )
    assert invalid.status_code == 422
