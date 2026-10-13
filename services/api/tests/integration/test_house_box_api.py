"""A wizard request becomes a geometry job and a finalized project version."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus, Operation
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401
from tests.integration.test_imports_api import run_all


def test_house_box_creates_a_project_job_and_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом у озера",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "l_shape",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["job"]["type"] == "build_house_box"
    assert accepted["height_mm"] == 6_000

    project_id = accepted["project_id"]
    before = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert before["name"] == "Дом у озера" and before["head_version"] is None

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["project_id"] == project_id and result["status"] == "executed"
    assert result["floor_plan"]["id"] == f"project-{project_id}-floor-1"
    assert len(result["floor_plan"]["walls"]) == 6

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    assert version["provenance"]["operation"] == "build_house_box"
    assert version["provenance"]["house_box"]["request"]["shape"] == "l_shape"
    floor_plan = api_client.get(f"/api/v1/projects/{project_id}/floor-plan", headers=actor.headers)
    assert floor_plan.status_code == 200, floor_plan.text
    assert floor_plan.json() == result["floor_plan"]
    legacy_floor_set = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers
    )
    assert legacy_floor_set.status_code == 200, legacy_floor_set.text
    assert len(legacy_floor_set.json()["levels"]) == 1
    takeoff_response = api_client.get(
        f"/api/v1/projects/{project_id}/construction-takeoff", headers=actor.headers
    )
    assert takeoff_response.status_code == 200, takeoff_response.text
    takeoff = takeoff_response.json()
    quantities = {line["code"]: line["quantity"] for line in takeoff["quantities"]}
    assert takeoff["version_id"] == result["version_id"]
    assert takeoff["floors"] == 2 and takeoff["floor_height_mm"] == 3_000
    assert quantities == {
        "footprint_area": 72.0,
        "total_floor_area": 144.0,
        "plan_wall_length": 40.0,
        "door_count": 0.0,
        "window_count": 0.0,
        "gross_wall_area": 240.0,
        "gross_wall_volume": 60.0,
    }
    assert takeoff["priced"] is False and takeoff["currency"] is None
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(result["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [op.operation_type for op in logged] == ["create_box", "create_box", "boolean"]


def test_house_box_api_reports_dimension_errors(api_client: TestClient, actor: Actor) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 1_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "length_mm" in response.text


def test_multifloor_stair_creates_aligned_plans_and_floor_scene_groups(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с лестницей",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "rectangle",
            "stair": {
                "width_mm": 1_000,
                "tread_depth_mm": 280,
                "step_count": 17,
                "placement": "center",
                "railing": True,
                "material_id": "interior.wood.oak-natural.v1",
            },
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version_id = (job.result or {})["version_id"]

    floors_response = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers
    )
    assert floors_response.status_code == 200, floors_response.text
    floors = floors_response.json()
    assert floors["version_id"] == version_id
    assert [level["elevation_mm"] for level in floors["levels"]] == [0, 3_000]
    assert floors["levels"][0]["plan"]["stairs"][0]["role"] == "up"
    assert floors["levels"][1]["plan"]["stairs"][0]["role"] == "down"
    assert (
        floors["levels"][0]["plan"]["stairs"][0]["outline"]
        == floors["levels"][1]["plan"]["stairs"][0]["outline"]
    )

    scene_response = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene_response.status_code == 200, scene_response.text
    nodes = {node["id"]: node for node in scene_response.json()["nodes"]}
    assert nodes["floor_1_group"]["kind"] == "group"
    assert nodes["floor_2_group"]["kind"] == "group"
    assert nodes["roof_group"]["kind"] == "group"
    assert nodes["floor_1"]["parent_id"] == "floor_1_group"
    assert nodes["stair_1_2"]["parent_id"] == "floor_1_group"
    assert nodes["stair_1_2"]["appearance"]["catalog_material_id"] == "interior.wood.oak-natural.v1"

    layout = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={"base_version_id": version_id, "room_count": 3},
        headers=actor.headers,
    )
    assert layout.status_code == 422, layout.text
    assert "not yet floor-elevation-aware" in layout.text

    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(version_id))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert len(logged) == 44
    assert sum(operation.operation_type == "shell" for operation in logged) == 2


def test_stair_rejects_impossible_or_unknown_material_before_enqueue(
    api_client: TestClient, actor: Actor
) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    impossible = api_client.post(
        "/api/v1/house-boxes",
        json={**base, "length_mm": 4_000, "stair": {"step_count": 17}},
        headers=actor.headers,
    )
    assert impossible.status_code == 422
    assert "do not fit" in impossible.text

    forged = api_client.post(
        "/api/v1/house-boxes",
        json={**base, "stair": {"material_id": "interior.wood.forged.v1"}},
        headers=actor.headers,
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["details"]["material_id"] == "interior.wood.forged.v1"


def test_rectangular_house_auto_layout_creates_an_immutable_plan_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Планируемый дом",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()
    (job,) = run_all(db_session, storage)
    base_version_id = str((job.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 3},
        headers=actor.headers,
    )

    assert response.status_code == 201, response.text
    layout = response.json()
    assert layout["sequence_no"] == 2 and layout["version_id"] != base_version_id
    assert len(layout["floor_plan"]["rooms"]) == 3
    assert len(layout["floor_plan"]["walls"]) == 6
    assert [opening["wall"] for opening in layout["floor_plan"]["openings"]] == [4, 5]
    current = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan", headers=actor.headers
    )
    assert current.json() == layout["floor_plan"]
    takeoff = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=actor.headers,
    ).json()
    quantities = {line["code"]: line["quantity"] for line in takeoff["quantities"]}
    assert quantities["door_count"] == 2
    assert quantities["plan_wall_length"] == 56
    assert quantities["total_floor_area"] == 96
    operations = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(layout["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert operations[-1].operation_type == "update_floor_plan"

    revised = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": layout["version_id"], "room_count": 2},
        headers=actor.headers,
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["sequence_no"] == 3
    assert len(revised.json()["floor_plan"]["rooms"]) == 2

    stale = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 2},
        headers=actor.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"


def test_l_house_auto_layout_records_decomposition_provenance(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "L house",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "l_shape",
        },
        headers=actor.headers,
    ).json()
    (job,) = run_all(db_session, storage)
    base_version_id = str((job.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 5},
        headers=actor.headers,
    )

    assert response.status_code == 201, response.text
    layout = response.json()
    assert len(layout["floor_plan"]["rooms"]) == 5
    assert len(layout["floor_plan"]["walls"]) == 11
    assert [opening["wall"] for opening in layout["floor_plan"]["openings"]] == [7, 8, 9, 10]
    assert layout["floor_plan"]["openings"][-1]["offset_mm"] == 3_260
    version = api_client.get(
        f"/api/v1/versions/{layout['version_id']}", headers=actor.headers
    ).json()
    provenance = version["provenance"]["floor_plan_layout"]
    assert provenance["kind"] == "lt_decomposition_v1"
    assert provenance["zone_room_counts"] == [2, 3]
    assert provenance["seam"] == {"a": [6_000.0, 4_000.0], "b": [0.0, 4_000.0]}


def test_floor_plan_is_not_claimed_before_the_house_version_exists(
    api_client: TestClient, actor: Actor
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 8_000,
            "width_mm": 6_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()

    response = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan", headers=actor.headers
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    takeoff = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=actor.headers,
    )
    assert takeoff.status_code == 404
    assert takeoff.json()["error"]["code"] == "not_found"


def test_construction_takeoff_hides_foreign_projects(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 8_000,
            "width_mm": 6_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()
    run_all(db_session, storage)
    stranger = make_actor(db_session)

    response = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=stranger.headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
