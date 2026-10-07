"""T-241: immutable multi-object hierarchy, groups and geometry instances."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ProjectVersion
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import project  # noqa: F401
from tests.integration.test_painting_api import imported_version

IDENTITY = [
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
]


def translated(x: float, y: float = 0, z: float = 0) -> list[list[float]]:
    matrix = [row[:] for row in IDENTITY]
    matrix[0][3] = x
    matrix[1][3] = y
    matrix[2][3] = z
    return matrix


def test_scene_edit_creates_an_immutable_hierarchy_and_reuses_instance_bytes(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    initial = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers)
    assert initial.status_code == 200, initial.text
    asset_id = initial.json()["nodes"][0]["resolved_asset_id"]

    response = api_client.post(
        f"/api/v1/models/{source_id}/scene",
        json={
            "label": "Assembly",
            "nodes": [
                {
                    "id": "assembly",
                    "name": "Assembly",
                    "kind": "group",
                    "transform": translated(10),
                },
                {
                    "id": "original",
                    "name": "Bracket",
                    "kind": "object",
                    "parent_id": "assembly",
                    "transform": translated(5),
                    "asset_id": asset_id,
                },
                {
                    "id": "instance_1",
                    "name": "Bracket instance",
                    "kind": "object",
                    "parent_id": "assembly",
                    "transform": translated(20),
                    "instance_of": "original",
                },
            ],
        },
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    made_id = body["version_id"]
    assert made_id != source_id
    assert body["parent_version_id"] == source_id
    assert body["nodes"][1]["world_transform"][0][3] == 15
    assert body["nodes"][2]["world_transform"][0][3] == 30
    assert body["nodes"][1]["resolved_asset_id"] == asset_id
    assert body["nodes"][2]["resolved_asset_id"] == asset_id

    made = db_session.get(ProjectVersion, made_id)
    source = db_session.get(ProjectVersion, source_id)
    assert made is not None and made.label == "Assembly"
    assert source is not None and "scene" not in source.provenance
    model_links = [link for link in made.assets if link.role is AssetRole.model]
    assert len(model_links) == 1  # two nodes, one content-addressed geometry object

    fetched = api_client.get(f"/api/v1/models/{made_id}/scene", headers=actor.headers)
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_scene_rejects_duplicate_cycles_missing_relations_and_foreign_assets(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    url = f"/api/v1/models/{version_id}/scene"
    asset_id = api_client.get(url, headers=actor.headers).json()["nodes"][0]["asset_id"]

    def post(nodes: list[dict[str, object]]) -> int:
        return api_client.post(url, json={"nodes": nodes}, headers=actor.headers).status_code

    direct = {
        "id": "part",
        "name": "Part",
        "kind": "object",
        "asset_id": asset_id,
    }
    assert post([direct, direct]) == 422
    assert post([{**direct, "parent_id": "missing"}]) == 422
    assert (
        post(
            [
                {"id": "a", "name": "A", "kind": "group", "parent_id": "b"},
                {"id": "b", "name": "B", "kind": "group", "parent_id": "a"},
                direct,
            ]
        )
        == 422
    )
    assert (
        post(
            [
                direct,
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "missing",
                },
            ]
        )
        == 422
    )

    stranger = make_actor(db_session)
    their_project = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(stranger.workspace.id), "name": "foreign"},
        headers=stranger.headers,
    ).json()["id"]
    their_version = imported_version(api_client, stranger, db_session, storage, their_project)
    foreign_asset = api_client.get(
        f"/api/v1/models/{their_version}/scene", headers=stranger.headers
    ).json()["nodes"][0]["asset_id"]
    foreign = post([{**direct, "asset_id": foreign_asset}])
    assert foreign == 404


def test_scene_is_private_and_read_only_for_viewers(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    url = f"/api/v1/models/{version_id}/scene"
    scene = api_client.get(url, headers=actor.headers).json()
    stranger = make_actor(db_session)
    assert api_client.get(url, headers=stranger.headers).status_code == 404
    viewer = make_actor(db_session, workspace=actor.workspace, role="viewer")
    assert api_client.get(url, headers=viewer.headers).status_code == 200
    assert (
        api_client.post(url, json={"nodes": scene["nodes"]}, headers=viewer.headers).status_code
        == 403
    )
