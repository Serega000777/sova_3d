"""Item 37: a measured site composition reaches the immutable scene and export assets."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401
from app.jobs import runner
from app.models import Asset, ProjectVersion
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_exports_api import box_stl
from tests.integration.test_printing_api import seed_version


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def _house_version(
    db: Session, storage: S3Storage, actor: Actor, cleanup_keys: list[str]
) -> ProjectVersion:
    project, source, asset = seed_version(db, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    return projects.create_version(
        db,
        user_id=actor.user.id,
        project_id=project.id,
        parent_version_id=source.id,
        provenance={
            "house_box": {
                "request": {
                    "length_mm": 10_000,
                    "width_mm": 8_000,
                    "floor_height_mm": 2_800,
                    "floors": 1,
                    "shape": "rectangle",
                    "stair": None,
                },
                "height_mm": 2_800,
            }
        },
        assets={AssetRole.model: asset.id},
    )


def _body() -> dict[str, object]:
    return {
        "plot_length_mm": 30_000,
        "plot_width_mm": 20_000,
        "corner_elevations_mm": [0, 100, 300, 50],
        "house_x_mm": 1_000,
        "house_y_mm": 0,
        "house_rotation_deg": 15,
        "path_points_mm": [[-15_000, -5_000], [-5_000, -2_000], [-3_000, 0]],
        "path_width_mm": 1_200,
        "fence_sides": ["north", "east", "south", "west"],
        "fence_height_mm": 1_500,
        "fence_post_spacing_mm": 2_500,
    }


def test_site_plan_builds_real_scene_objects_and_preserves_house(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = _house_version(db_session, storage, actor, cleanup_keys)
    accepted = api_client.post(
        f"/api/v1/models/{source.id}/site-plan", json=_body(), headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and made.parent_version_id == source.id
    assert (made.provenance or {})["site_plan"]["house_dimensions_mm"] == [10_000.0, 8_000.0]
    scene = api_client.get(f"/api/v1/models/{made.id}/scene", headers=actor.headers).json()
    by_id = {node["id"]: node for node in scene["nodes"]}
    assert {
        "site_root",
        "site_house",
        "site_house_pad",
        "site_terrain",
        "site_path",
        "site_fence",
    } <= set(by_id)
    assert by_id["object_1"]["parent_id"] == "site_house"
    assert by_id["site_house"]["world_transform"][0][3] == 1_000
    assert by_id["site_house"]["world_transform"][2][3] > 0
    assert by_id["site_terrain"]["parent_id"] == "site_root"
    original_house_asset_id = by_id["object_1"]["resolved_asset_id"]
    original_site_asset_ids = set(result["asset_ids"].values())
    for asset_id in result["asset_ids"].values():
        asset = db_session.get(Asset, uuid.UUID(asset_id))
        assert asset is not None
        cleanup_keys.append(asset.storage_key)

    recomposed_body = {
        **_body(),
        "corner_elevations_mm": [200, 50, 0, 100],
        "house_x_mm": -1_000,
        "fence_sides": ["north", "south"],
    }
    recomposed = api_client.post(
        f"/api/v1/models/{made.id}/site-plan",
        json=recomposed_body,
        headers=actor.headers,
    )
    assert recomposed.status_code == 202, recomposed.text
    recomposed_job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert recomposed_job is not None and recomposed_job.status is JobStatus.succeeded
    recomposed_result = recomposed_job.result or {}
    rebuilt = db_session.get(ProjectVersion, uuid.UUID(recomposed_result["version_id"]))
    assert rebuilt is not None and rebuilt.parent_version_id == made.id
    rebuilt_scene = api_client.get(
        f"/api/v1/models/{rebuilt.id}/scene", headers=actor.headers
    ).json()
    rebuilt_by_id = {node["id"]: node for node in rebuilt_scene["nodes"]}
    assert rebuilt_by_id["object_1"]["resolved_asset_id"] == original_house_asset_id
    assert rebuilt_by_id["site_house"]["world_transform"][0][3] == -1_000
    assert "site_fence" in rebuilt_by_id
    rebuilt_asset_ids = {
        node["resolved_asset_id"]
        for node in rebuilt_scene["nodes"]
        if node["resolved_asset_id"] is not None
    }
    assert original_site_asset_ids.isdisjoint(rebuilt_asset_ids)
    for asset_id in recomposed_result["asset_ids"].values():
        asset = db_session.get(Asset, uuid.UUID(asset_id))
        assert asset is not None
        cleanup_keys.append(asset.storage_key)


def test_site_plan_fails_closed_for_auth_lineage_fit_and_stale_head(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = _house_version(db_session, storage, actor, cleanup_keys)
    url = f"/api/v1/models/{source.id}/site-plan"
    stranger = make_actor(db_session)
    viewer = make_actor(db_session, workspace=actor.workspace, role="viewer")
    assert api_client.post(url, json=_body(), headers=stranger.headers).status_code == 404
    assert api_client.post(url, json=_body(), headers=viewer.headers).status_code == 403

    too_small = {**_body(), "plot_length_mm": 10_000, "plot_width_mm": 8_000}
    assert api_client.post(url, json=too_small, headers=actor.headers).status_code == 422

    accepted = api_client.post(url, json=_body(), headers=actor.headers)
    assert accepted.status_code == 202
    model_link = next(link for link in source.assets if link.role is AssetRole.model)
    projects.create_version(
        db_session,
        user_id=actor.user.id,
        project_id=source.project_id,
        parent_version_id=source.id,
        provenance=source.provenance,
        assets={AssetRole.model: model_link.asset_id},
    )
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.failed
    assert (job.error or {})["code"] == "site_plan_conflict"
