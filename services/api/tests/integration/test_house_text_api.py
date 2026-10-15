"""Item 41: a house description becomes a verifiable proposal before any job exists."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.core import WorkspaceRole
from app.models.execution import AIRequest, Job, JobStatus
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401
from tests.integration.test_imports_api import run_all

RU = "Создай двухэтажный прямоугольный дом 12 × 8 м, высота этажа 300 см"
EN = "Build a rectangular house 12000 mm x 8 m, 2 floors, floor height 3 m"
CANONICAL = {
    "length_mm": 12_000,
    "width_mm": 8_000,
    "floor_height_mm": 3_000,
    "floors": 2,
    "shape": "rectangle",
}


def house_jobs(db: Session) -> list[Job]:
    return db.query(Job).filter(Job.type == "build_house_box").all()


def refusal(response: Any, status: int = 422) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    return error


def test_text_proposal_is_read_only_and_apply_enqueues_the_exact_house(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    workspace = str(actor.workspace.id)
    projects_before = len(
        projects.list_projects(db_session, user_id=actor.user.id, workspace_id=actor.workspace.id)
    )
    proposed = api_client.post(
        "/api/v1/house-boxes/text-proposal",
        json={"workspace_id": workspace, "prompt": RU},
        headers=actor.headers,
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["request"] == CANONICAL
    assert proposal["language"] == "ru"
    assert proposal["total_height_mm"] == 6_000 and proposal["footprint_area_m2"] == 96.0
    assert proposal["job_created"] is False and proposal["ai_used"] is False
    assert [entry["field"] for entry in proposal["diff"]] == [
        "length_mm", "width_mm", "floor_height_mm", "floors", "shape",
    ]  # fmt: skip
    assert {entry["field"]: entry["before"] for entry in proposal["diff"]} == dict.fromkeys(
        CANONICAL
    )
    height = next(entry for entry in proposal["diff"] if entry["field"] == "floor_height_mm")
    assert height["label_ru"] == "Высота этажа" and height["source"] == "высота этажа 300 см"
    assert "12 000 × 8 000 мм" in proposal["summary_ru"]
    english = api_client.post(
        "/api/v1/house-boxes/text-proposal",
        json={"workspace_id": workspace, "prompt": EN},
        headers=actor.headers,
    )
    assert english.status_code == 200, english.text
    assert english.json()["request"] == CANONICAL and english.json()["language"] == "en"
    # Proposal never spends AI, never creates a project and never queues work.
    assert house_jobs(db_session) == []
    assert db_session.query(AIRequest).count() == 0
    assert (
        len(
            projects.list_projects(
                db_session, user_id=actor.user.id, workspace_id=actor.workspace.id
            )
        )
        == projects_before
    )

    applied = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={"workspace_id": workspace, "prompt": RU, "request": proposal["request"]},
        headers={**actor.headers, "Idempotency-Key": "item41-text-house"},
    )
    assert applied.status_code == 202, applied.text
    accepted = applied.json()
    assert accepted["job"]["type"] == "build_house_box" and accepted["height_mm"] == 6_000
    (queued,) = house_jobs(db_session)
    assert queued.input["request"] == {**CANONICAL, "stair": None}
    assert queued.input["source"] == {"kind": "text_proposal", "prompt": RU, "language": "ru"}
    assert db_session.query(AIRequest).count() == 0

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version = api_client.get(
        f"/api/v1/versions/{(job.result or {})['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    assert version["provenance"]["house_box"]["request"] == {**CANONICAL, "stair": None}
    project = api_client.get(f"/api/v1/projects/{accepted['project_id']}", headers=actor.headers)
    assert project.json()["name"] == "Дом по описанию"


@pytest.mark.parametrize(
    ("prompt", "reason"),
    [
        ("дом 12 x 8, высота этажа 3 м, 2 этажа", "missing_unit"),
        ("дом 12 x 8 м, высота 6 м, 2 этажа", "ambiguous_height"),
        ("Build a house 12 x 8 m, 2 floors, floor height 3 m, length 13 m", "conflict"),
        ("Build a house 12 x 8 m, floor height 3 m", "missing_fields"),
        ("дом 12 x 8 м, высота этажа 3 м, 5 этажей", "out_of_range"),
        ("Т-образный дом 12 x 8 м, высота этажа 3 м, 2 этажа", "unsupported_shape"),
        ("Нарисуй что-нибудь", "not_a_house"),
    ],
)
def test_text_proposal_rejects_ambiguous_text_without_job(
    api_client: TestClient, actor: Actor, db_session: Session, prompt: str, reason: str
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes/text-proposal",
        json={"workspace_id": str(actor.workspace.id), "prompt": prompt},
        headers=actor.headers,
    )
    error = refusal(response)
    assert error["code"] == "validation_failed"
    assert error["details"]["reason"] == reason
    assert house_jobs(db_session) == []


@pytest.mark.parametrize(
    ("request_body", "status"),
    [
        ({**CANONICAL, "floors": 3}, 422),
        ({**CANONICAL, "length_mm": 12_001}, 422),
        ({**CANONICAL, "shape": "l_shape"}, 422),
        ({**CANONICAL, "stair": {"width_mm": 1_000}}, 422),
        ({**CANONICAL, "floor_height_mm": 3000.5}, 422),
        ({**CANONICAL, "floor_height_mm": "3000"}, 422),
        ({**CANONICAL, "floor_height_mm": 3000.0}, 422),
        ({k: v for k, v in CANONICAL.items() if k != "floors"}, 422),
    ],
)
def test_forged_or_altered_proposal_is_refused_before_enqueue(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    request_body: dict[str, Any],
    status: int,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={"workspace_id": str(actor.workspace.id), "prompt": RU, "request": request_body},
        headers=actor.headers,
    )
    assert refusal(response, status)["code"] == "validation_failed"
    assert house_jobs(db_session) == []


def test_apply_reparses_text_and_rejects_unknown_top_level_fields(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    workspace = str(actor.workspace.id)
    mismatch = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={
            "workspace_id": workspace,
            "prompt": EN.replace("2 floors", "3 floors"),
            "request": CANONICAL,
        },
        headers=actor.headers,
    )
    assert refusal(mismatch)["details"]["reason"] == "proposal_mismatch"
    unparsable = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={"workspace_id": workspace, "prompt": "дом побольше", "request": CANONICAL},
        headers=actor.headers,
    )
    assert refusal(unparsable)["code"] == "validation_failed"
    extra = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={"workspace_id": workspace, "prompt": RU, "request": CANONICAL, "label": "x"},
        headers=actor.headers,
    )
    assert refusal(extra)["code"] == "validation_failed"
    assert house_jobs(db_session) == []


def test_text_house_respects_workspace_ownership_and_empty_head(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    workspace = str(actor.workspace.id)
    stranger = make_actor(db_session)
    for path, body in (
        ("text-proposal", {"workspace_id": workspace, "prompt": RU}),
        ("text-apply", {"workspace_id": workspace, "prompt": RU, "request": CANONICAL}),
    ):
        response = api_client.post(
            f"/api/v1/house-boxes/{path}", json=body, headers=stranger.headers
        )
        assert refusal(response, 404)["code"] == "not_found"
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    blocked = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={"workspace_id": workspace, "prompt": RU, "request": CANONICAL},
        headers=viewer.headers,
    )
    assert refusal(blocked, 403)["code"] == "forbidden"

    # A foreign project cannot be the target, even from my own workspace id.
    foreign = projects.create_project(
        db_session, user_id=stranger.user.id, workspace_id=stranger.workspace.id, name="theirs"
    )
    smuggled = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={
            "workspace_id": workspace,
            "project_id": str(foreign.id),
            "prompt": RU,
            "request": CANONICAL,
        },
        headers=actor.headers,
    )
    assert refusal(smuggled, 404)["code"] == "not_found"
    assert house_jobs(db_session) == []

    # An empty own project accepts the house; once it has a head, a second apply conflicts.
    empty = projects.create_project(
        db_session, user_id=actor.user.id, workspace_id=actor.workspace.id, name="empty"
    )
    body = {"workspace_id": workspace, "project_id": str(empty.id), "prompt": EN}
    proposal = api_client.post(
        "/api/v1/house-boxes/text-proposal", json=body, headers=actor.headers
    )
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["project_id"] == str(empty.id)
    applied = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={**body, "request": proposal.json()["request"]},
        headers=actor.headers,
    )
    assert applied.status_code == 202, applied.text
    assert applied.json()["project_id"] == str(empty.id)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    stale = api_client.post(
        "/api/v1/house-boxes/text-apply",
        json={**body, "request": proposal.json()["request"]},
        headers=actor.headers,
    )
    assert refusal(stale, 409)["details"]["reason"] == "project_has_head"
    assert len(house_jobs(db_session)) == 1
