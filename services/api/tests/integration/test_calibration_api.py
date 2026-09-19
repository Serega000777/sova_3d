"""E20 (F-028/F-029): print the coupon, measure it, and the printer's numbers are used."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def default_profile(api_client: TestClient, actor: Actor) -> dict[str, Any]:
    response = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Desk MINI",
            "default_material_id": "pla",
            "is_default": True,
        },
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    profile: dict[str, Any] = response.json()
    return profile


def test_the_coupon_is_built_as_a_project_of_its_own(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    profile = default_profile(api_client, actor)
    response = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/calibration-print", headers=actor.headers
    )
    assert response.status_code == 202, response.text
    started = response.json()
    assert started["job"]["type"] == "execute_plan"
    assert {f["id"] for f in started["features"]} >= {"hole_5_mm", "peg_8_mm", "length_60_mm"}

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    summary = api_client.get(f"/api/v1/projects/{started['project_id']}", headers=actor.headers)
    assert summary.status_code == 200
    head = summary.json()["head_version"]
    assert head["label"] == "Calibration coupon"
    assert head["provenance"]["calibration_for_profile_id"] == profile["id"]
    types = [op["type"] for op in (job.result or {})["plan"]["operations"]]
    assert types.count("add_hole") == 3 and types.count("boolean") == 2


def test_calipers_teach_the_profile_and_every_screw_hole_after_that_uses_it(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    profile = default_profile(api_client, actor)
    recorded = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/calibration",
        json={"hole_3_mm": 2.65, "hole_5_mm": 4.65, "hole_8_mm": 7.65, "length_60_mm": 59.85},
        headers=actor.headers,
    )
    assert recorded.status_code == 200, recorded.text
    learned = recorded.json()["calibration"]
    assert learned["hole_undersize_mm"] == 0.35
    assert learned["shrinkage_pct"] == 0.25
    assert learned["samples"] == 4

    # the planner: "holes for M5" on this workspace's default printer is 5.5 + 0.35
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 60x40x8 mm with 2 holes for M5", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    holes = [op for op in (job.result or {})["plan"]["operations"] if op["type"] == "add_hole"]
    assert holes and all(h["diameter_mm"] == 5.85 for h in holes)
    version_id = str((job.result or {})["version_id"])

    # the engineer: the same number, and it says where it came from
    api_client.post(
        f"/api/v1/models/{version_id}/engineering",
        json={"question": "holes for M3 screws"},
        headers=actor.headers,
    )
    (advice,) = run_all(db_session, storage)
    assert advice.status is JobStatus.succeeded, advice.error
    answer = (advice.result or {})["report"]["answer"]
    assert answer["numbers"]["diameter_mm"] == 3.75  # 3.4 + 0.35, not 3.6
    assert "measured on your printer" in answer["summary"]


def test_bad_readings_are_refused_and_nothing_is_learned(
    api_client: TestClient, actor: Actor
) -> None:
    profile = default_profile(api_client, actor)
    response = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/calibration",
        json={"hole_8_mm": 3.0},
        headers=actor.headers,
    )
    assert response.status_code == 422
    unchanged = api_client.get(f"/api/v1/printer-profiles/{profile['id']}", headers=actor.headers)
    assert unchanged.json()["calibration"] == {}
