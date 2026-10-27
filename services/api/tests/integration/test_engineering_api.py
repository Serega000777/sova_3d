"""E16 (F-005): ask the engineer about a version; the answer is measured, the fix is valid."""

from __future__ import annotations

from typing import Any

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from worker import engineering as measuring

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.engineering import EngineeringReportRecord
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, alembic_config, table_names
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def built_version(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> tuple[str, str]:
    """A plate with a hole, built through the kernel; returns (version_id, body name)."""
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Plate 60x40x8 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    version_id = str((built.result or {})["version_id"])
    body = str((built.result or {})["bodies"][-1]["name"])
    return version_id, body


def with_hole(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    version_id: str,
    body: str,
    diameter: float,
) -> str:
    response = api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={
            "operations": [
                {
                    "type": "add_hole",
                    "target": body,
                    "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
                    "position_mm": [10, 10],
                    "diameter_mm": diameter,
                }
            ],
            "label": "hole",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (edited,) = run_all(db_session, storage)
    assert edited.status is JobStatus.succeeded, edited.error
    return str((edited.result or {})["version_id"])


def ask(api_client: TestClient, actor: Actor, version_id: str, **body: Any) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/engineering", json=body, headers=actor.headers
    )


def test_migration_0011_adds_the_reports_table(migrated_db: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0010")
    assert "engineering_reports" not in table_names(migrated_db)
    command.upgrade(cfg, "head")
    assert "engineering_reports" in table_names(migrated_db)


def test_the_engineer_measures_the_part_and_answers_in_the_users_language(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id, _ = built_version(api_client, actor, db_session, storage, project)
    response = ask(api_client, actor, version_id, question="Эта стенка слишком тонкая?")
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["report"]

    # measured, not guessed: a solid 60 × 40 × 8 plate is 8 mm thick everywhere
    assert report["facts"]["watertight"] is True
    assert report["facts"]["walls"]["median_mm"] == 8.0
    assert report["facts"]["mass_g"]["pla"] > 0
    answer = report["answer"]
    assert answer["intent"] == "walls" and answer["language"] == "ru"
    assert answer["verdict"] == "no"  # 8 mm is plenty for a structural PLA wall
    assert "8 mm" in answer["summary"]

    # and it is on record for the version
    listing = api_client.get(f"/api/v1/models/{version_id}/engineering", headers=actor.headers)
    assert listing.status_code == 200
    (row,) = listing.json()
    assert row["question"] == "Эта стенка слишком тонкая?"
    assert row["report"]["answer"]["verdict"] == "no"
    record = db_session.get(EngineeringReportRecord, row["id"])
    assert record is not None and record.job_id == job.id

    load_response = ask(
        api_client, actor, version_id, question="Выдержит 20 кг?", material_id="pla"
    )
    assert load_response.status_code == 202, load_response.text
    (load_job,) = run_all(db_session, storage)
    assert load_job.status is JobStatus.succeeded, load_job.error
    load_answer = (load_job.result or {})["report"]["answer"]
    assert load_answer["numbers"]["load_kg"] == 20
    assert (
        load_answer["numbers"]["bending_stress_mpa"]
        > load_answer["numbers"]["allowable_stress_mpa"]
    )
    assert load_answer["risk_region"]["region"] == {
        "kind": "box",
        "min_mm": [0.0, 0.0, 0.0],
        "max_mm": [6.0, 40.0, 8.0],
    }
    reinforcement = load_answer["fix"]
    assert reinforcement is not None
    assert reinforcement["operations"] == [
        {"type": "set_dimensions", "target": "body", "height_mm": 12.7}
    ]

    applied_response = api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={"operations": reinforcement["operations"], "label": reinforcement["label"]},
        headers=actor.headers,
    )
    assert applied_response.status_code == 202, applied_response.text
    (applied,) = run_all(db_session, storage)
    assert applied.status is JobStatus.succeeded, applied.error
    reinforced_id = str((applied.result or {})["version_id"])

    reinforced_response = ask(
        api_client, actor, reinforced_id, question="Выдержит 20 кг?", material_id="pla"
    )
    assert reinforced_response.status_code == 202, reinforced_response.text
    (reinforced_job,) = run_all(db_session, storage)
    assert reinforced_job.status is JobStatus.succeeded, reinforced_job.error
    reinforced_answer = (reinforced_job.result or {})["report"]["answer"]
    assert reinforced_answer["verdict"] == "yes"
    assert reinforced_answer["fix"] is None
    assert reinforced_answer["numbers"]["section_height_mm"] == 12.7


def test_a_measured_shell_fix_survives_the_real_job_and_edit_path(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    monkeypatch: Any,
) -> None:
    version_id, body = built_version(api_client, actor, db_session, storage, project)
    shell_response = api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={
            "operations": [
                {
                    "type": "shell",
                    "target": body,
                    "thickness_mm": 1.2,
                    "open_face": {"kind": "face_by_normal", "axis": "z", "sign": "-"},
                }
            ],
            "label": "thin shell",
        },
        headers=actor.headers,
    )
    assert shell_response.status_code == 202, shell_response.text
    (shell_job,) = run_all(db_session, storage)
    assert shell_job.status is JobStatus.succeeded, shell_job.error
    shell_version_id = str((shell_job.result or {})["version_id"])
    shell_operation = next(
        op for op in (shell_job.result or {})["plan"]["operations"] if op["type"] == "shell"
    )

    measured_wall = 1.2

    def measured(*_args: Any, **_kwargs: Any) -> measuring.EngineeringFacts:
        stats = measuring.WallStats(
            samples=40,
            min_mm=measured_wall,
            p5_mm=measured_wall,
            median_mm=measured_wall,
            max_mm=measured_wall,
            limit_mm=2.7,
            thin_fraction=1.0 if measured_wall < 2.7 else 0.0,
        )
        return measuring.EngineeringFacts(
            ok=True,
            bbox_mm=[60, 40, 8],
            volume_mm3=10_000,
            area_mm2=8_000,
            watertight=True,
            faces=12,
            walls=stats,
            slenderness=50,
            mass_g={"pla": 12.4},
        )

    monkeypatch.setattr(measuring, "run_in_sandbox", measured)
    response = ask(
        api_client,
        actor,
        shell_version_id,
        question="Выдержит ли стенка 8 кг?",
        material_id="pla",
    )
    assert response.status_code == 202, response.text
    (advice_job,) = run_all(db_session, storage)
    assert advice_job.status is JobStatus.succeeded, advice_job.error
    answer = (advice_job.result or {})["report"]["answer"]
    assert answer["verdict"] == "yes"
    assert answer["fix"]["operations"] == [
        {
            "type": "set_parameter",
            "operation": shell_operation["id"],
            "parameter": "thickness_mm",
            "value": 2.7,
        }
    ]

    applied_response = api_client.post(
        f"/api/v1/models/{shell_version_id}/edits",
        json={"operations": answer["fix"]["operations"], "label": answer["fix"]["label"]},
        headers=actor.headers,
    )
    assert applied_response.status_code == 202, applied_response.text
    (applied,) = run_all(db_session, storage)
    assert applied.status is JobStatus.succeeded, applied.error
    applied_operations = (applied.result or {})["plan"]["operations"]
    assert applied_operations[-1] == {
        "id": applied_operations[-1]["id"],
        "type": "set_parameter",
        "schema_version": 1,
        "operation": shell_operation["id"],
        "parameter": "thickness_mm",
        "value": 2.7,
    }

    measured_wall = 2.7
    reinforced_id = str((applied.result or {})["version_id"])
    response = ask(
        api_client,
        actor,
        reinforced_id,
        question="Стенка всё ещё слишком тонкая?",
        material_id="pla",
    )
    assert response.status_code == 202, response.text
    (reinforced_job,) = run_all(db_session, storage)
    reinforced = (reinforced_job.result or {})["report"]["answer"]
    assert reinforced["verdict"] == "no" and reinforced["fix"] is None


def test_a_screw_question_offers_a_fix_the_edit_endpoint_accepts(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id, body = built_version(api_client, actor, db_session, storage, project)
    holed = with_hole(api_client, actor, db_session, storage, version_id, body, diameter=4.0)

    ask(api_client, actor, holed, question="holes for M5 screws")
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    answer = (job.result or {})["report"]["answer"]
    assert answer["intent"] == "fastener"
    assert answer["numbers"]["diameter_mm"] == 5.7
    fix = answer["fix"]
    assert fix is not None
    assert fix["operations"][0]["type"] == "set_parameter"
    assert fix["operations"][0]["parameter"] == "diameter_mm"

    # the fix is what the inspector would send: apply it as it is
    response = api_client.post(
        f"/api/v1/models/{holed}/edits",
        json={"operations": fix["operations"], "label": fix["label"]},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (applied,) = run_all(db_session, storage)
    assert applied.status is JobStatus.succeeded, applied.error
    plan = (applied.result or {})["plan"]
    assert plan["operations"][-1]["type"] == "set_parameter"
    assert plan["operations"][-1]["value"] == 5.7


def test_without_a_question_the_engineer_reviews_the_part(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id, body = built_version(api_client, actor, db_session, storage, project)
    odd = with_hole(api_client, actor, db_session, storage, version_id, body, diameter=4.9)
    ask(api_client, actor, odd, purpose="a bracket for the garden, outside in the sun")
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["report"]
    assert report["answer"] is None
    assert report["materials"][0]["id"] == "asa"  # outdoors, in the sun
    assert report["holes"][0]["diameter_mm"] == 4.9
    flagged = [rec for rec in report["recommendations"] if rec["intent"] == "fastener"]
    assert flagged and flagged[0]["fix"] is not None


def test_bad_inputs_are_refused_before_the_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id, _ = built_version(api_client, actor, db_session, storage, project)
    assert ask(api_client, actor, version_id, material_id="unobtainium").status_code == 422
    assert ask(api_client, actor, version_id, question="x" * 501).status_code == 422
    bad_region = {"region": {"kind": "box", "min_mm": [0, 0], "max_mm": [1, 1, 1]}}
    assert ask(api_client, actor, version_id, region=bad_region).status_code == 422
