"""T-014 project CRUD with workspace authorization; T-015 immutable versions with lineage."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.models import Asset, Project
from app.models.core import WorkspaceRole
from app.models.versioning import AssetKind
from tests.integration.conftest import Actor, make_actor


def create_project(api_client: TestClient, actor: Actor, name: str = "Organizer") -> Response:
    response: Response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": name},
        headers=actor.headers,
    )
    return response


def create_version(api_client: TestClient, actor: Actor, project_id: str, **body: Any) -> Response:
    response: Response = api_client.post(
        f"/api/v1/projects/{project_id}/versions", json=body, headers=actor.headers
    )
    return response


def make_asset(db: Session, workspace_id: uuid.UUID, seed: str) -> Asset:
    sha = (seed * 64)[:64]
    asset = Asset(
        workspace_id=workspace_id,
        kind=AssetKind.original,
        sha256=sha,
        storage_key=f"ws/{workspace_id}/assets/{sha[:2]}/{sha}.stl",
        mime="model/stl",
        format="stl",
        byte_size=10,
    )
    db.add(asset)
    db.flush()
    return asset


# --- T-014 -----------------------------------------------------------------------------------


def test_project_crud_roundtrip(api_client: TestClient, actor: Actor) -> None:
    created = create_project(api_client, actor)
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["units"] == "mm" and project["head_version_id"] is None

    fetched = api_client.get(f"/api/v1/projects/{project['id']}", headers=actor.headers)
    assert fetched.status_code == 200
    assert fetched.json()["head_version"] is None

    listed = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert [p["id"] for p in listed.json()] == [project["id"]]

    patched = api_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Desk organizer", "description": "6 slots"},
        headers=actor.headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Desk organizer"
    assert patched.json()["description"] == "6 slots"

    deleted = api_client.delete(f"/api/v1/projects/{project['id']}", headers=actor.headers)
    assert deleted.status_code == 204
    gone = api_client.get(f"/api/v1/projects/{project['id']}", headers=actor.headers)
    assert gone.status_code == 404
    listed = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert listed.json() == []


def test_projects_are_workspace_scoped(api_client: TestClient, db_session: Session) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    project_id = create_project(api_client, owner).json()["id"]

    assert (
        api_client.get(f"/api/v1/projects/{project_id}", headers=stranger.headers).status_code
        == 404
    )
    assert (
        api_client.patch(
            f"/api/v1/projects/{project_id}", json={"name": "x"}, headers=stranger.headers
        ).status_code
        == 404
    )
    assert (
        api_client.delete(f"/api/v1/projects/{project_id}", headers=stranger.headers).status_code
        == 404
    )
    assert (
        api_client.get(
            "/api/v1/projects",
            params={"workspace_id": str(owner.workspace.id)},
            headers=stranger.headers,
        ).status_code
        == 404
    )
    assert (
        api_client.post(
            "/api/v1/projects",
            json={"workspace_id": str(owner.workspace.id), "name": "intruder"},
            headers=stranger.headers,
        ).status_code
        == 404
    )
    assert db_session.get(Project, uuid.UUID(project_id)) is not None


def test_role_matrix(api_client: TestClient, db_session: Session) -> None:
    viewer = make_actor(db_session, role=WorkspaceRole.viewer)
    editor = make_actor(db_session, role=WorkspaceRole.editor)

    assert create_project(api_client, viewer).status_code == 403
    listed = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(viewer.workspace.id)},
        headers=viewer.headers,
    )
    assert listed.status_code == 200

    project_id = create_project(api_client, editor).json()["id"]
    assert (
        api_client.delete(f"/api/v1/projects/{project_id}", headers=editor.headers).status_code
        == 403
    )


# --- T-015 -----------------------------------------------------------------------------------


def test_versions_are_append_only_with_lineage(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = create_project(api_client, actor).json()["id"]
    model_a = make_asset(db_session, actor.workspace.id, "a")
    model_b = make_asset(db_session, actor.workspace.id, "b")

    v1 = create_version(
        api_client,
        actor,
        project_id,
        label="initial",
        assets={"model": str(model_a.id)},
        provenance={"source": "upload"},
    )
    assert v1.status_code == 201, v1.text
    v1_body = v1.json()
    assert v1_body["sequence_no"] == 1 and v1_body["parent_version_id"] is None
    assert v1_body["state"] == "finalized" and v1_body["finalized_at"]
    assert v1_body["provenance"] == {"source": "upload", "parent_version_id": None}
    assert v1_body["assets"] == [{"asset_id": str(model_a.id), "role": "model"}]

    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] == v1_body["id"]
    assert head["head_version"]["sequence_no"] == 1

    # Parent defaults to the head; the head advances.
    v2_body = create_version(
        api_client, actor, project_id, label="edit", assets={"model": str(model_b.id)}
    ).json()
    assert v2_body["sequence_no"] == 2
    assert v2_body["parent_version_id"] == v1_body["id"]
    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] == v2_body["id"]

    # Branching from v1 does not move the head off v2.
    v3_body = create_version(
        api_client, actor, project_id, parent_version_id=v1_body["id"], label="branch"
    ).json()
    assert v3_body["sequence_no"] == 3 and v3_body["parent_version_id"] == v1_body["id"]
    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] == v2_body["id"]

    lineage = api_client.get(
        f"/api/v1/versions/{v3_body['id']}/lineage", headers=actor.headers
    ).json()
    assert [v["sequence_no"] for v in lineage] == [3, 1]

    timeline = api_client.get(
        f"/api/v1/projects/{project_id}/versions", headers=actor.headers
    ).json()
    assert [v["sequence_no"] for v in timeline] == [3, 2, 1]


def test_draft_versions_can_be_finalized_later(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = create_project(api_client, actor).json()["id"]
    draft = create_version(api_client, actor, project_id, finalize=False).json()
    assert draft["state"] == "draft" and draft["finalized_at"] is None
    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] is None

    # A draft cannot be a parent.
    blocked = create_version(api_client, actor, project_id, parent_version_id=draft["id"])
    assert blocked.status_code == 409

    finalized = api_client.post(
        f"/api/v1/versions/{draft['id']}/finalize", headers=actor.headers
    ).json()
    assert finalized["state"] == "finalized" and finalized["finalized_at"]
    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] == draft["id"]

    # Finalize is idempotent.
    again = api_client.post(f"/api/v1/versions/{draft['id']}/finalize", headers=actor.headers)
    assert again.status_code == 200 and again.json()["finalized_at"] == finalized["finalized_at"]


def test_version_asset_must_belong_to_workspace(
    api_client: TestClient, db_session: Session
) -> None:
    owner = make_actor(db_session)
    other = make_actor(db_session)
    foreign_asset = make_asset(db_session, other.workspace.id, "f")
    project_id = create_project(api_client, owner).json()["id"]

    response = create_version(
        api_client, owner, project_id, assets={"model": str(foreign_asset.id)}
    )
    assert response.status_code == 404
    assert response.json()["error"]["details"]["resource"] == "asset"
    timeline = api_client.get(
        f"/api/v1/projects/{project_id}/versions", headers=owner.headers
    ).json()
    assert timeline == []


def test_versions_are_workspace_scoped(api_client: TestClient, db_session: Session) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    project_id = create_project(api_client, owner).json()["id"]
    version_id = create_version(api_client, owner, project_id).json()["id"]

    for path in (
        f"/api/v1/versions/{version_id}",
        f"/api/v1/versions/{version_id}/lineage",
        f"/api/v1/projects/{project_id}/versions",
    ):
        assert api_client.get(path, headers=stranger.headers).status_code == 404
    assert create_version(api_client, stranger, project_id).status_code == 404
    assert (
        api_client.post(f"/api/v1/versions/{version_id}/finalize", headers=stranger.headers)
    ).status_code == 404
