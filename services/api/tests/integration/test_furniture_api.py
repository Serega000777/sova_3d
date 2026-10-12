"""Furniture catalogue placement uses the immutable scene graph end to end."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.engineering.floor_plan import floor_plan_from_house_box
from app.engineering.house_box import HouseBoxRequest
from app.jobs import runner
from app.models import Asset, ProjectVersion
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_exports_api import box_stl
from tests.integration.test_printing_api import seed_version


def run_all(db: Session, storage: S3Storage):
    done = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def test_catalogue_places_real_geometry_and_scene_export_preserves_transform(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    catalogue = api_client.get("/api/v1/furniture", headers=actor.headers)
    assert catalogue.status_code == 200
    assert {item["kind"] for item in catalogue.json()} == {
        "chair",
        "table",
        "sofa",
        "bed",
        "cabinet",
    }
    _, source, source_asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source_asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{source.id}/furniture",
        json={
            "kind": "chair",
            "x_mm": 1000,
            "y_mm": 2000,
            "rotation_deg": 90,
            "width_mm": 500,
            "depth_mm": 600,
            "height_mm": 900,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and made.parent_version_id == source.id
    scene = api_client.get(f"/api/v1/models/{made.id}/scene", headers=actor.headers).json()
    assert len(scene["nodes"]) == 2
    chair = next(node for node in scene["nodes"] if node["id"] == result["node_id"])
    assert chair["world_transform"][0][3] == 1000
    assert chair["world_transform"][1][3] == 2000
    assert chair["world_transform"][0][0] == pytest.approx(0, abs=1e-12)
    assert chair["footprint_mm"] == [500.0, 600.0]
    furniture_asset = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert furniture_asset is not None
    cleanup_keys.append(furniture_asset.storage_key)

    exported = api_client.post(
        f"/api/v1/models/{made.id}/exports",
        json={"format": "stl"},
        headers=actor.headers,
    )
    assert exported.status_code == 202, exported.text
    (export_job,) = run_all(db_session, storage)
    assert export_job.status is JobStatus.succeeded, export_job.error
    export_asset = db_session.get(Asset, uuid.UUID((export_job.result or {})["asset_id"]))
    assert export_asset is not None
    cleanup_keys.append(export_asset.storage_key)
    mesh = trimesh.load_mesh(
        trimesh.util.wrap_as_stream(storage.get(export_asset.storage_key)),
        file_type="stl",
        process=False,
    )
    assert mesh.bounds[1][0] == pytest.approx(1300, abs=1)
    assert mesh.bounds[1][1] == pytest.approx(2250, abs=1)


def test_furniture_placement_is_private_and_editor_only(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    url = f"/api/v1/models/{version.id}/furniture"
    stranger = make_actor(db_session)
    viewer = make_actor(db_session, workspace=actor.workspace, role="viewer")
    assert api_client.post(url, json={"kind": "table"}, headers=stranger.headers).status_code == 404
    assert api_client.post(url, json={"kind": "table"}, headers=viewer.headers).status_code == 403


def _version_with_plan(
    db: Session, storage: S3Storage, actor: Actor, cleanup_keys: list[str]
) -> ProjectVersion:
    project, source, asset = seed_version(db, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    plan = floor_plan_from_house_box(
        HouseBoxRequest(length_mm=4_000, width_mm=5_000, floor_height_mm=2_800, floors=1),
        plan_id="room-1",
        name="Room",
    )
    return projects.create_version(
        db,
        user_id=actor.user.id,
        project_id=project.id,
        parent_version_id=source.id,
        provenance={"floor_plan": plan.model_dump(mode="json")},
        assets={AssetRole.model: asset.id},
    )


def test_plan_drag_placement_enforces_clearance_and_rechecks_in_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = _version_with_plan(db_session, storage, actor, cleanup_keys)
    url = f"/api/v1/models/{source.id}/furniture"
    collision = api_client.post(
        url,
        json={
            "kind": "chair",
            "x_mm": 380,
            "y_mm": 2_500,
            "floor_plan_id": "room-1",
            "clearance_mm": 100,
        },
        headers=actor.headers,
    )
    assert collision.status_code == 422, collision.text
    assert collision.json()["error"]["details"]["placement_conflict"] == "wall_clearance"

    accepted = api_client.post(
        url,
        json={
            "kind": "chair",
            "x_mm": 2_000,
            "y_mm": 2_500,
            "rotation_deg": 90,
            "width_mm": 500,
            "depth_mm": 600,
            "height_mm": 900,
            "floor_plan_id": "room-1",
            "clearance_mm": 300,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and made.parent_version_id == source.id
    furniture_asset = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert furniture_asset is not None
    cleanup_keys.append(furniture_asset.storage_key)
    blocked_by_chair = api_client.post(
        f"/api/v1/models/{made.id}/furniture",
        json={
            "kind": "table",
            "x_mm": 2_800,
            "y_mm": 2_500,
            "floor_plan_id": "room-1",
            "clearance_mm": 300,
        },
        headers=actor.headers,
    )
    assert blocked_by_chair.status_code == 422, blocked_by_chair.text
    assert (
        blocked_by_chair.json()["error"]["details"]["placement_conflict"] == "furniture_clearance"
    )


def test_plan_drag_input_pair_and_stale_plan_fail_closed(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = _version_with_plan(db_session, storage, actor, cleanup_keys)
    url = f"/api/v1/models/{source.id}/furniture"
    missing_pair = api_client.post(
        url,
        json={"kind": "chair", "clearance_mm": 200},
        headers=actor.headers,
    )
    stale_plan = api_client.post(
        url,
        json={"kind": "chair", "floor_plan_id": "old", "clearance_mm": 200},
        headers=actor.headers,
    )
    assert missing_pair.status_code == 422
    assert stale_plan.status_code == 409


def test_plan_drag_job_rejects_a_concurrent_head_change(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = _version_with_plan(db_session, storage, actor, cleanup_keys)
    accepted = api_client.post(
        f"/api/v1/models/{source.id}/furniture",
        json={
            "kind": "chair",
            "x_mm": 2_000,
            "y_mm": 2_500,
            "floor_plan_id": "room-1",
            "clearance_mm": 300,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    model_link = next(link for link in source.assets if link.role is AssetRole.model)
    projects.create_version(
        db_session,
        user_id=actor.user.id,
        project_id=source.project_id,
        parent_version_id=source.id,
        provenance=source.provenance,
        assets={AssetRole.model: model_link.asset_id},
    )

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "furniture_placement_conflict"
    assert "reload the plan" in (job.error or {})["message"]
