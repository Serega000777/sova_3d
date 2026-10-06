"""T-237b/F-087: plan markup persists server-side with project access control."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import WorkspaceMember, WorkspaceRole
from app.models.plan_annotations import PlanAnnotations
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import box_bytes, upload
from tests.integration.test_photo_api import png_bytes


def _pin(id_: str = "a1") -> dict[str, object]:
    return {
        "id": id_,
        "author": "Alice",
        "created_at": "2026-01-01T00:00:00.000Z",
        "status": "open",
        "note": "check this wall",
        "colour": "#ff4d4f",
        "kind": "pin",
        "at": [100.0, 200.0],
        "number": 1,
    }


def _dimension(id_: str = "a2") -> dict[str, object]:
    return {
        "id": id_,
        "author": "Alice",
        "created_at": "2026-01-01T00:00:01.000Z",
        "status": "open",
        "note": "",
        "colour": "#5b9cff",
        "kind": "dimension",
        "from": [0.0, 0.0],
        "to": [1000.0, 0.0],
    }


def test_annotations_roundtrip_and_project_isolation(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Floor plan"},
        headers=actor.headers,
    ).json()["id"]
    path = f"/api/v1/projects/{project_id}/plans/room-1/annotations"

    empty = api_client.get(path, headers=actor.headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "annotations": [],
        "revision": 0,
        "updated_at": None,
        "updated_by": None,
    }

    saved = api_client.put(
        path, json={"annotations": [_pin()], "base_revision": 0}, headers=actor.headers
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert [a["id"] for a in body["annotations"]] == ["a1"]
    assert body["revision"] == 1
    assert body["updated_by"] == str(actor.user.id)
    assert body["updated_at"]

    fetched = api_client.get(path, headers=actor.headers)
    assert fetched.status_code == 200
    assert [a["id"] for a in fetched.json()["annotations"]] == ["a1"]

    # A current full replace succeeds and advances the compare-and-swap revision.
    replaced = api_client.put(
        path, json={"annotations": [_dimension()], "base_revision": 1}, headers=actor.headers
    )
    assert replaced.status_code == 200
    assert [a["id"] for a in replaced.json()["annotations"]] == ["a2"]
    assert replaced.json()["revision"] == 2

    # A writer that loaded revision 1 cannot erase revision 2.
    stale = api_client.put(
        path, json={"annotations": [_pin("stale")], "base_revision": 1}, headers=actor.headers
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"] == {
        "plan_id": "room-1",
        "base_revision": 1,
        "current_revision": 2,
    }
    assert [a["id"] for a in api_client.get(path, headers=actor.headers).json()["annotations"]] == [
        "a2"
    ]

    # only one row backs the (project, plan) pair
    assert db_session.query(PlanAnnotations).count() == 1

    # a second plan in the same project gets its own row
    other_plan_path = f"/api/v1/projects/{project_id}/plans/room-2/annotations"
    assert api_client.get(other_plan_path, headers=actor.headers).json()["annotations"] == []
    api_client.put(
        other_plan_path,
        json={"annotations": [_pin("b1")], "base_revision": 0},
        headers=actor.headers,
    )
    assert db_session.query(PlanAnnotations).count() == 2
    # the first plan's markup is untouched
    assert [a["id"] for a in api_client.get(path, headers=actor.headers).json()["annotations"]] == [
        "a2"
    ]

    # a bad annotation (missing the shape fields the "pin" kind requires) is rejected
    bad = api_client.put(
        path,
        json={"annotations": [{**_pin(), "at": None}], "base_revision": 2},
        headers=actor.headers,
    )
    assert bad.status_code == 422

    # a stranger with no membership cannot see or write this project's markup
    foreign = make_actor(db_session)
    assert api_client.get(path, headers=foreign.headers).status_code == 404
    assert (
        api_client.put(
            path, json={"annotations": [], "base_revision": 2}, headers=foreign.headers
        ).status_code
        == 404
    )

    # a foreign project id entirely is likewise 404, not a different project's data
    unrelated_project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(foreign.workspace.id), "name": "Someone else's project"},
        headers=foreign.headers,
    ).json()["id"]
    cross_path = f"/api/v1/projects/{unrelated_project_id}/plans/room-1/annotations"
    assert api_client.get(cross_path, headers=actor.headers).status_code == 404
    assert (
        api_client.put(
            cross_path, json={"annotations": [], "base_revision": 0}, headers=actor.headers
        ).status_code
        == 404
    )

    # a viewer in the project's workspace may read but not write
    db_session.add(
        WorkspaceMember(
            workspace_id=actor.workspace.id, user_id=foreign.user.id, role=WorkspaceRole.viewer
        )
    )
    db_session.flush()
    assert api_client.get(path, headers=foreign.headers).status_code == 200
    assert (
        api_client.put(
            path, json={"annotations": [], "base_revision": 2}, headers=foreign.headers
        ).status_code
        == 403
    )


def test_annotation_photos_and_3d_anchors_are_project_scoped(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Inspection"},
        headers=actor.headers,
    ).json()["id"]
    version_id = api_client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"label": "Room", "finalize": True},
        headers=actor.headers,
    ).json()["id"]
    photo_id = upload(api_client, actor, png_bytes(), "crack.png", "image/png")
    path = f"/api/v1/projects/{project_id}/plans/room-1/annotations"
    anchored = {
        **_pin(),
        "photo_asset_ids": [photo_id],
        "model_anchor_mm": [125.5, -42.0, 830.0],
        "model_version_id": version_id,
    }
    saved = api_client.put(
        path, json={"annotations": [anchored], "base_revision": 0}, headers=actor.headers
    )
    assert saved.status_code == 200, saved.text
    annotation = saved.json()["annotations"][0]
    assert annotation["photo_asset_ids"] == [photo_id]
    assert annotation["model_anchor_mm"] == [125.5, -42.0, 830.0]
    assert annotation["model_version_id"] == version_id

    missing_version = api_client.put(
        path,
        json={
            "annotations": [{**_pin(), "model_anchor_mm": [0, 0, 0]}],
            "base_revision": 1,
        },
        headers=actor.headers,
    )
    assert missing_version.status_code == 422

    model_id = upload(api_client, actor, box_bytes("stl"), "not-a-photo.stl", "model/stl")
    wrong_format = api_client.put(
        path,
        json={"annotations": [{**_pin(), "photo_asset_ids": [model_id]}], "base_revision": 1},
        headers=actor.headers,
    )
    assert wrong_format.status_code == 422

    other_project = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Other"},
        headers=actor.headers,
    ).json()["id"]
    other_version = api_client.post(
        f"/api/v1/projects/{other_project}/versions",
        json={"finalize": True},
        headers=actor.headers,
    ).json()["id"]
    wrong_version = api_client.put(
        path,
        json={
            "annotations": [
                {
                    **_pin(),
                    "model_anchor_mm": [0, 0, 0],
                    "model_version_id": other_version,
                }
            ],
            "base_revision": 1,
        },
        headers=actor.headers,
    )
    assert wrong_version.status_code == 404

    stranger = make_actor(db_session)
    foreign_photo = upload(api_client, stranger, png_bytes(), "private.png", "image/png")
    cross_workspace = api_client.put(
        path,
        json={
            "annotations": [{**_pin(), "photo_asset_ids": [foreign_photo]}],
            "base_revision": 1,
        },
        headers=actor.headers,
    )
    assert cross_workspace.status_code == 404
