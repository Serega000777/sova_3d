"""F-020: calibrated camera evidence becomes a real exact part proposal."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import Job
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import project  # noqa: F401
from tests.integration.test_project_references import _body, _image_asset


def test_calibrated_width_and_height_propose_and_build_a_mounting_plate(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    missing = api_client.post(
        f"/api/v1/projects/{project}/functional-part-proposal",
        json={"problem": "Нужна крепёжная пластина"},
        headers=actor.headers,
    )
    assert missing.status_code == 422

    asset = _image_asset(db_session, actor)
    reference = _body(asset)
    reference["measurements"].append(
        {
            "id": "10000000-0000-4000-8000-000000000002",
            "label": "Высота места",
            "points": [[0.5, 0.2], [0.5, 0.7]],
        }
    )
    saved = api_client.put(
        f"/api/v1/projects/{project}/reference", json=reference, headers=actor.headers
    )
    assert saved.status_code == 200, saved.text

    proposed = api_client.post(
        f"/api/v1/projects/{project}/functional-part-proposal",
        json={"problem": "Нужна крепёжная пластина", "clearance_mm": 0.5},
        headers=actor.headers,
    )
    assert proposed.status_code == 200, proposed.text
    result = proposed.json()
    assert result["recognizes_contents"] is False
    assert result["physical_validation_required"] is True
    assert result["evidence"] == [
        {"label": "Window width", "value_mm": 72.0},
        {"label": "Высота места", "value_mm": 80.0},
    ]
    assert result["drawing"]["width_mm"] == 71
    assert result["drawing"]["height_mm"] == 79
    assert len(result["drawing"]["holes"]) == 4

    accepted = api_client.post(
        f"/api/v1/projects/{project}/dimensioned-drawing",
        json=result["drawing"],
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = db_session.get(Job, accepted.json()["job_id"])
    assert job is not None
    assert [operation["type"] for operation in job.input["plan"]["operations"]] == [
        "extrude",
        "add_hole",
        "add_hole",
        "add_hole",
        "add_hole",
    ]


def test_unlabelled_photo_distances_are_not_treated_as_dimensions(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    asset = _image_asset(db_session, actor, "d")
    reference = _body(asset)
    reference["measurements"][0]["label"] = "место"
    api_client.put(
        f"/api/v1/projects/{project}/reference", json=reference, headers=actor.headers
    )
    response = api_client.post(
        f"/api/v1/projects/{project}/functional-part-proposal",
        json={"problem": "make a bracket"},
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["required_labels"] == ["width", "height"]
