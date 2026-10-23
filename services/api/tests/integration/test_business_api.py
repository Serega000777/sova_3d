"""F-050: a product line is costed only from stored physical print evidence."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.printing import AnalysisKind, PrintAnalysisRecord
from app.services import projects
from tests.integration.conftest import Actor, make_actor


def _costed_version(db: Session, actor: Actor, name: str = "Desk hook"):
    project = projects.create_project(
        db, user_id=actor.user.id, workspace_id=actor.workspace.id, name=name
    )
    version = projects.create_version(db, user_id=actor.user.id, project_id=project.id)
    analysis = PrintAnalysisRecord(
        workspace_id=actor.workspace.id,
        project_version_id=version.id,
        kind=AnalysisKind.analysis,
        score=Decimal("92"),
        status="green",
        report={
            "metrics": {
                "mass_g": 42.5,
                "print_time_min": 120,
                "total_cost": 2,
                "currency": "USD",
            }
        },
    )
    db.add(analysis)
    db.flush()
    return project, version, analysis


def test_business_plan_costs_a_real_version_without_claiming_demand(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project, version, analysis = _costed_version(db_session, actor)
    response = api_client.post(
        "/api/v1/business/plan",
        json={
            "workspace_id": str(actor.workspace.id),
            "version_ids": [str(version.id)],
            "target_margin_pct": 50,
            "machine_rate_per_hour": 3,
            "labour_per_unit": 1,
            "packaging_per_unit": 1,
        },
        headers=actor.headers,
    )

    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["demand_claimed"] is False
    assert plan["currency"] == "USD"
    assert len(plan["products"]) == 1
    product = plan["products"][0]
    assert product["project_id"] == str(project.id)
    assert product["analysis_id"] == str(analysis.id)
    assert Decimal(product["unit_cost"]) == Decimal("10.00")
    assert Decimal(product["recommended_price"]) == Decimal("20.00")
    assert Decimal(product["gross_profit_per_unit"]) == Decimal("10.00")
    assert product["render_ready"] is False


def test_business_plan_requires_analysis_and_workspace_access(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project = projects.create_project(
        db_session, user_id=actor.user.id, workspace_id=actor.workspace.id, name="Unknown cost"
    )
    version = projects.create_version(
        db_session, user_id=actor.user.id, project_id=project.id
    )
    body = {
        "workspace_id": str(actor.workspace.id),
        "version_ids": [str(version.id)],
    }
    missing = api_client.post("/api/v1/business/plan", json=body, headers=actor.headers)
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == (
        "every business product needs a completed print analysis"
    )

    stranger = make_actor(db_session)
    hidden = api_client.post("/api/v1/business/plan", json=body, headers=stranger.headers)
    assert hidden.status_code == 404
