"""E33 (F-035/F-036): the catalogue over HTTP, a case built by request or by the sentence
"Сделай корпус под Raspberry Pi 4 с вентилятором 40 мм", the lid kept as a part of its own,
and an edit of the case that keeps both bodies."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import AIRequest, AIRequestStatus, Job, JobStatus, Operation
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401

# --- F-035: the catalogue ------------------------------------------------------------------


def test_components_are_searchable_in_both_languages(api_client: TestClient, actor: Actor) -> None:
    response = api_client.get("/api/v1/components", headers=actor.headers)
    assert response.status_code == 200, response.text
    everything = response.json()
    assert {c["kind"] for c in everything} >= {"board", "fan", "display", "motor", "sensor"}
    pi = next(c for c in everything if c["id"] == "raspberry-pi-4b")
    assert pi["size_mm"] == [85.0, 56.0, 1.5] and pi["screw"] == "M2.5" and len(pi["holes"]) == 4
    assert {c["side"] for c in pi["cutouts"]} == {"+x", "-x", "-y"}

    hits = api_client.get("/api/v1/components?q=pi&language=ru", headers=actor.headers).json()
    assert [c["id"] for c in hits] == [
        "raspberry-pi-4b",
        "raspberry-pi-5",
        "raspberry-pi-zero-2w",
        "raspberry-pi-pico",
    ]
    assert "USB" in hits[0]["note"] and "рёбрах" in hits[0]["note"]  # the Russian note
    assert api_client.get("/api/v1/components?q=teapot", headers=actor.headers).json() == []


# --- F-036: the generator over HTTP ------------------------------------------------------


def build(
    api_client: TestClient, actor: Actor, body: dict[str, Any], **headers: str
) -> tuple[int, Any]:
    response = api_client.post(
        "/api/v1/enclosures",
        json={"workspace_id": str(actor.workspace.id), **body},
        headers={**actor.headers, **headers},
    )
    return response.status_code, response.json()


def test_a_case_for_a_pi_becomes_a_project_with_tray_and_lid(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    status, accepted = build(
        api_client, actor, {"component_id": "raspberry-pi-4b", "fan_id": "fan-40"}
    )
    assert status == 202, accepted
    assert accepted["job"]["type"] == "build_enclosure"
    assert accepted["outer_mm"] == [91.0, 62.0, 26.5] and accepted["posts"] == 4
    assert accepted["lid"] is True and accepted["fan"] == "fan-40"
    assert "Ethernet" in accepted["cutouts"] and "microSD" in accepted["cutouts"]

    # a new project, named after the board, holds the case
    project_id = accepted["project_id"]
    summary = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert summary["name"] == "Raspberry Pi 4 Model B case"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["enclosure"]["posts"] == 4 and result["status"] == "executed"
    (lid,) = result["parts"]
    assert lid["name"] == "lid" and lid["asset_id"] and lid["brep_asset_id"]

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    provenance = version["provenance"]
    assert provenance["operation"] == "build_enclosure"
    assert provenance["expected_outputs"] == ["tray", "lid"]
    assert provenance["component_id"] == "raspberry-pi-4b"
    assert provenance["enclosure"]["request"]["fan_id"] == "fan-40"
    assert [p["name"] for p in provenance["parts"]] == ["lid"]
    # the tray is the version's model, the lid downloads on its own
    for asset_id in (result["model_asset_id"], lid["asset_id"], lid["brep_asset_id"]):
        download = api_client.get(f"/api/v1/assets/{asset_id}/download", headers=actor.headers)
        assert download.status_code in (200, 307), download.text
    # the plan is the version's operation log: editable like any AI-built model
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(result["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert logged[0].operation_type == "create_box" and logged[1].operation_type == "shell"
    assert {op.operation_type for op in logged} >= {"fillet", "add_hole", "boolean"}
    assert summary["head_version"] is None  # before the job; after it the case is the head
    after = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert after["head_version"]["id"] == result["version_id"]


def test_the_sentence_routes_to_the_generator_not_the_planner(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Сделай корпус под Raspberry Pi 4 с вентилятором 40 мм", "units": "mm"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    queued = db_session.get(Job, uuid.UUID(accepted["job_id"]))
    assert queued is not None and queued.type == "build_enclosure"
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["project_id"] == project and result["enclosure"]["fan"] == "fan-40"

    request = db_session.get(AIRequest, uuid.UUID(accepted["ai_request_id"]))
    assert request is not None
    assert request.status is AIRequestStatus.executed
    assert str(request.result_version_id) == result["version_id"]
    assert request.output_plan is not None
    assert request.output_plan["expected_outputs"] == ["tray", "lid"]

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["label"] == "Сделай корпус под Raspberry Pi 4 с вентилятором 40 мм"
    assert version["provenance"]["ai_request_id"] == accepted["ai_request_id"]
    operations = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(result["version_id"]))
        .all()
    )
    assert operations and all(op.ai_request_id == request.id for op in operations)


def test_editing_the_case_keeps_both_bodies(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    status, accepted = build(api_client, actor, {"component_id": "arduino-uno-r3"})
    assert status == 202, accepted
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version_id = (job.result or {})["version_id"]

    response = api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={
            "operations": [{"type": "translate", "target": "tray", "offset_mm": [0, 0, 5]}],
            "label": "Lift the tray",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    child = api_client.get(
        f"/api/v1/versions/{(job.result or {})['version_id']}", headers=actor.headers
    ).json()
    assert child["parent_version_id"] == version_id
    assert child["provenance"]["expected_outputs"] == ["tray", "lid"]
    assert [p["name"] for p in child["provenance"]["parts"]] == ["lid"]


def test_a_sentence_edit_of_the_case_changes_the_tray_and_keeps_the_lid(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    status, accepted = build(api_client, actor, {"component_id": "raspberry-pi-pico"})
    assert status == 202, accepted
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version_id = (job.result or {})["version_id"]

    response = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/ai-commands",
        json={"prompt": "Скругли рёбра на 1 мм", "units": "mm"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    child = api_client.get(
        f"/api/v1/versions/{(job.result or {})['version_id']}", headers=actor.headers
    ).json()
    assert child["parent_version_id"] == version_id
    # the planner edited the tray (the main body, not a vent slot or the lid) ...
    request = db_session.get(AIRequest, uuid.UUID(response.json()["ai_request_id"]))
    assert request is not None and request.output_plan is not None
    fillets = [op for op in request.output_plan["operations"] if op["type"] == "fillet"]
    assert fillets[-1]["target"] == "tray" and fillets[-1]["radius_mm"] == 1
    # ... and the lid is still a part of the new version
    assert child["provenance"]["expected_outputs"] == ["tray", "lid"]
    assert [p["name"] for p in child["provenance"]["parts"]] == ["lid"]


def test_bad_requests_fail_before_any_job(api_client: TestClient, actor: Actor) -> None:
    status, body = build(api_client, actor, {"component_id": "teapot"})
    assert status == 422 and body["error"]["code"] == "validation_failed"
    status, body = build(api_client, actor, {"component_id": "fan-40"})
    assert status == 422 and "not something a case" in body["error"]["message"]
    status, body = build(api_client, actor, {"component_id": "arduino-nano", "fan_id": "fan-80"})
    assert status == 422 and body["error"]["details"]["fans"] == ["fan-30", "fan-40"]
    status, body = build(api_client, actor, {"component_id": "arduino-nano", "wall_mm": 0.2})
    assert status == 422


def test_a_stranger_cannot_build_into_another_workspace(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    stranger = make_actor(db_session)
    response = api_client.post(
        "/api/v1/enclosures",
        json={"workspace_id": str(actor.workspace.id), "component_id": "arduino-nano"},
        headers=stranger.headers,
    )
    assert response.status_code == 404, response.text


def test_the_same_key_returns_the_same_job(api_client: TestClient, actor: Actor) -> None:
    key = f"case-{uuid.uuid4()}"
    first = build(
        api_client, actor, {"component_id": "raspberry-pi-pico"}, **{"Idempotency-Key": key}
    )
    second = build(
        api_client, actor, {"component_id": "raspberry-pi-pico"}, **{"Idempotency-Key": key}
    )
    assert first[0] == second[0] == 202
    assert first[1]["job"]["job_id"] == second[1]["job"]["job_id"]
    assert first[1]["project_id"] == second[1]["project_id"]  # and no second empty project
