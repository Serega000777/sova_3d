"""A drawn wall perimeter becomes a geometry job and a finalized project version."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus, Operation
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401
from tests.integration.test_imports_api import run_all

RECTANGLE = [
    {"a": [0, 0], "b": [6000, 0], "thickness_mm": 120},
    {"a": [6000, 0], "b": [6000, 4000], "thickness_mm": 120},
    {"a": [6000, 4000], "b": [0, 4000], "thickness_mm": 120},
    {"a": [0, 4000], "b": [0, 0], "thickness_mm": 120},
]


def test_house_walls_creates_a_project_job_and_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-walls",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с нуля",
            "walls": RECTANGLE,
            "floor_height_mm": 3_000,
            "floors": 1,
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["job"]["type"] == "build_house_walls"
    assert accepted["height_mm"] == 3_000
    assert accepted["wall_count"] == 4

    project_id = accepted["project_id"]
    before = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert before["name"] == "Дом с нуля" and before["head_version"] is None

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["project_id"] == project_id and result["status"] == "executed"
    assert result["floor_plan"]["rooms"][0]["outline"] == [
        [0.0, 0.0],
        [6000.0, 0.0],
        [6000.0, 4000.0],
        [0.0, 4000.0],
    ]

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    assert version["provenance"]["operation"] == "build_house_walls"
    assert version["provenance"]["house_walls"]["wall_count"] == 4
    floor_plan = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plan", headers=actor.headers
    )
    assert floor_plan.status_code == 200, floor_plan.text
    assert floor_plan.json() == result["floor_plan"]
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(result["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [op.operation_type for op in logged].count("create_box") == 4
    assert [op.operation_type for op in logged].count("boolean") == 3


def test_house_walls_api_rejects_an_open_perimeter(api_client: TestClient, actor: Actor) -> None:
    response = api_client.post(
        "/api/v1/house-walls",
        json={
            "workspace_id": str(actor.workspace.id),
            "walls": RECTANGLE[:3],  # never closes back to (0, 0)
            "floor_height_mm": 3_000,
            "floors": 1,
        },
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "closed perimeter" in response.text


def test_house_walls_api_rejects_too_few_walls(api_client: TestClient, actor: Actor) -> None:
    response = api_client.post(
        "/api/v1/house-walls",
        json={
            "workspace_id": str(actor.workspace.id),
            "walls": RECTANGLE[:2],
            "floor_height_mm": 3_000,
            "floors": 1,
        },
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_house_walls_api_reports_dimension_errors(api_client: TestClient, actor: Actor) -> None:
    response = api_client.post(
        "/api/v1/house-walls",
        json={
            "workspace_id": str(actor.workspace.id),
            "walls": RECTANGLE,
            "floor_height_mm": 1_000,
            "floors": 1,
        },
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "floor_height_mm" in response.text
