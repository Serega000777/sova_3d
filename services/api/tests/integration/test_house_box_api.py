"""A wizard request becomes a geometry job and a finalized project version."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus, Operation
from app.storage import S3Storage
from tests.integration.conftest import Actor
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

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    assert version["provenance"]["operation"] == "build_house_box"
    assert version["provenance"]["house_box"]["request"]["shape"] == "l_shape"
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
