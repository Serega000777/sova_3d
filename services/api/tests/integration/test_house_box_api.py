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
    floor_plan = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plan", headers=actor.headers
    )
    assert floor_plan.status_code == 200, floor_plan.text
    assert floor_plan.json() == result["floor_plan"]
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
