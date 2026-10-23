"""F-050: a product line is costed only from stored physical print evidence."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.printing import AnalysisKind, PrintAnalysisRecord
from app.models.versioning import Asset, AssetKind, AssetRole, VersionAsset
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
    assert product["render_asset_id"] is None
    assert product["analysis_status"] == "green"
    assert Decimal(product["printability_score"]) == Decimal("92")
    assert product["material_id"] is None
    assert product["printer_profile_id"] is None
    assert product["production_instructions"] == [
        {
            "ru": "Производите неизменяемую версию v1; не подменяйте её другой версией.",
            "en": "Manufacture immutable version v1; do not substitute another version.",
        },
        {
            "ru": "Ожидаемый результат по сохранённому анализу: 42.5 г, 120 мин.",
            "en": "Expected output: 42.5 g and 120 min from the stored analysis.",
        },
        {
            "ru": "Проверка печати: green, оценка 92; осмотрите физическое изделие перед выдачей.",
            "en": (
                "Printability gate: green, score 92; "
                "inspect the physical output before fulfilment."
            ),
        },
    ]

    thumbnail = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.derived,
        sha256="b" * 64,
        storage_key=f"business/{version.id}/iso.png",
        mime="image/png",
        format="png",
        byte_size=8,
        created_by=actor.user.id,
    )
    db_session.add(thumbnail)
    db_session.flush()
    db_session.add(
        VersionAsset(
            version_id=version.id,
            asset_id=thumbnail.id,
            role=AssetRole.thumbnail,
            thumbnail_angle="iso",
        )
    )
    db_session.flush()

    with_render = api_client.post(
        "/api/v1/business/plan",
        json={
            "workspace_id": str(actor.workspace.id),
            "version_ids": [str(version.id)],
        },
        headers=actor.headers,
    )
    assert with_render.status_code == 200, with_render.text
    rendered_product = with_render.json()["products"][0]
    assert rendered_product["render_ready"] is True
    assert rendered_product["render_asset_id"] == str(thumbnail.id)


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
