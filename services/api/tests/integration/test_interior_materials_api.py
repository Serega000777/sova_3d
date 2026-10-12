"""Item 22: catalogue finishes persist on immutable scene objects."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Job, ProjectVersion
from app.models.core import WorkspaceRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_imports_api import project  # noqa: F401
from tests.integration.test_painting_api import imported_version


def test_catalogue_and_texture_are_bounded_and_content_addressed(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/interior-materials")
    assert response.status_code == 200
    materials = response.json()
    assert 10 <= len(materials) <= 16
    assert len({item["id"] for item in materials}) == len(materials)
    assert {tab for item in materials for tab in item["tabs"]} == {
        "wall",
        "floor",
        "furniture",
        "tile",
    }
    paint = next(item for item in materials if item["kind"] == "paint")
    assert paint["base_color"].startswith("#") and paint["texture_url"] is None
    textured = next(item for item in materials if item["texture_url"])
    texture = api_client.get(textured["texture_url"])
    assert texture.status_code == 200 and texture.headers["content-type"] == "image/png"
    assert texture.headers["cache-control"].endswith("immutable")
    assert hashlib.sha256(texture.content).hexdigest() == textured["texture_sha256"]
    assert (
        api_client.get("/api/v1/interior-materials/textures/" + "0" * 64 + ".png").status_code
        == 422
    )


def test_assign_carry_clear_and_drop_interior_material(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    material_id = "interior.wood.oak-natural.v1"
    assigned = api_client.post(
        f"/api/v1/models/{source_id}/interior-material",
        json={"scene_node_id": "object_1", "catalog_material_id": material_id},
        headers=actor.headers,
    )
    assert assigned.status_code == 201, assigned.text
    body = assigned.json()
    made_id = body["version_id"]
    node = body["nodes"][0]
    assert node["appearance"]["catalog_material_id"] == material_id
    assert node["appearance"]["texture_url"].endswith(".png")
    assert node["asset_id"] == node["resolved_asset_id"]
    made = db_session.get(ProjectVersion, made_id)
    assert made is not None
    assert made.provenance["scene"]["schema_version"] == 2
    assert made.provenance["interior_material_edit"]["source_version_id"] == source_id
    accepted = api_client.post(
        f"/api/v1/models/{made_id}/exports",
        json={"format": "glb"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    export_job = db_session.get(Job, accepted.json()["job_id"])
    assert export_job is not None
    assert export_job.input["scene"][0]["appearance"]["catalog_material_id"] == material_id

    # A public scene edit cannot forge appearance, but the stable node id carries the exact
    # server snapshot across rename/transform edits.
    forged = api_client.post(
        f"/api/v1/models/{made_id}/scene",
        json={"nodes": [{**node, "appearance": {"base_color": "#000000"}}]},
        headers=actor.headers,
    )
    assert forged.status_code == 422
    renamed_node = {**node, "name": "Oak chair"}
    renamed = api_client.post(
        f"/api/v1/models/{made_id}/scene",
        json={"nodes": [renamed_node]},
        headers=actor.headers,
    )
    assert renamed.status_code == 201, renamed.text
    renamed_id = renamed.json()["version_id"]
    assert renamed.json()["nodes"][0]["appearance"]["catalog_material_id"] == material_id

    no_op = api_client.post(
        f"/api/v1/models/{renamed_id}/interior-material",
        json={"scene_node_id": "object_1", "catalog_material_id": material_id},
        headers=actor.headers,
    )
    assert no_op.status_code == 422
    cleared = api_client.post(
        f"/api/v1/models/{renamed_id}/interior-material",
        json={"scene_node_id": "object_1", "catalog_material_id": None},
        headers=actor.headers,
    )
    assert cleared.status_code == 201 and cleared.json()["nodes"][0]["appearance"] is None

    # Removing the only assigned id while keeping another object never guesses by asset/name.
    dropped = api_client.post(
        f"/api/v1/models/{renamed_id}/scene",
        json={
            "nodes": [
                {
                    "id": "replacement",
                    "name": "Oak chair",
                    "kind": "object",
                    "asset_id": node["resolved_asset_id"],
                }
            ]
        },
        headers=actor.headers,
    )
    assert dropped.status_code == 201
    assert dropped.json()["nodes"][0]["appearance"] is None
    dropped_row = db_session.get(ProjectVersion, dropped.json()["version_id"])
    assert dropped_row is not None
    assert dropped_row.provenance["scene_edit"]["dropped_material_node_ids"] == ["object_1"]


def test_material_assignment_fails_closed_for_invalid_targets_and_permissions(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    url = f"/api/v1/models/{version_id}/interior-material"
    assert (
        api_client.post(
            url,
            json={
                "scene_node_id": "missing",
                "catalog_material_id": "interior.paint.warm-white-matte.v1",
            },
            headers=actor.headers,
        ).status_code
        == 422
    )
    assert (
        api_client.post(
            url,
            json={"scene_node_id": "object_1", "catalog_material_id": "unknown"},
            headers=actor.headers,
        ).status_code
        == 422
    )
    assert (
        api_client.post(
            url,
            json={"scene_node_id": "object_1", "catalog_material_id": None},
            headers=actor.headers,
        ).status_code
        == 422
    )

    scene = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers).json()
    asset_id = scene["nodes"][0]["resolved_asset_id"]
    grouped = api_client.post(
        f"/api/v1/models/{version_id}/scene",
        json={
            "nodes": [
                {"id": "root", "name": "Root", "kind": "group"},
                {
                    "id": "part",
                    "name": "Part",
                    "kind": "object",
                    "parent_id": "root",
                    "asset_id": asset_id,
                },
            ]
        },
        headers=actor.headers,
    ).json()
    group_url = f"/api/v1/models/{grouped['version_id']}/interior-material"
    assert (
        api_client.post(
            group_url,
            json={
                "scene_node_id": "root",
                "catalog_material_id": "interior.paint.warm-white-matte.v1",
            },
            headers=actor.headers,
        ).status_code
        == 422
    )
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    assert (
        api_client.post(
            group_url,
            json={
                "scene_node_id": "part",
                "catalog_material_id": "interior.paint.warm-white-matte.v1",
            },
            headers=viewer.headers,
        ).status_code
        == 403
    )
    stranger = make_actor(db_session)
    assert (
        api_client.post(
            group_url,
            json={
                "scene_node_id": "part",
                "catalog_material_id": "interior.paint.warm-white-matte.v1",
            },
            headers=stranger.headers,
        ).status_code
        == 404
    )
