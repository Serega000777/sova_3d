from fastapi.testclient import TestClient

from tests.integration.conftest import Actor


def test_pricing_catalogue_and_quote_are_authenticated_and_shadow_only(
    api_client: TestClient, actor: Actor
) -> None:
    assert api_client.get("/api/v1/pricing").status_code == 401

    response = api_client.get("/api/v1/pricing", headers=actor.headers)
    assert response.status_code == 200, response.text
    catalogue = response.json()
    assert catalogue["version"] == "2026-10-29.v2"
    assert catalogue["charging_mode"] == "shadow"
    assert catalogue["commercial_mode"] == "proposal"
    assert catalogue["currency"] == "credit"
    assert len(catalogue["actions"]) >= 30
    prices = {row["action_type"]: row for row in catalogue["actions"]}
    assert prices["generate_mesh"]["credits"] == "30"
    assert prices["slice_preview"]["credits"] == "1"
    markets = {row["market"]: row for row in catalogue["markets"]}
    assert markets["ru"]["currency"] == "RUB"
    assert markets["international"]["currency"] == "USD"
    assert markets["ru"]["subscriptions"][2] == {
        "code": "pro",
        "monthly_price_minor": 149000,
        "included_credits": 1500,
        "seats": 1,
        "title_ru": "Профи",
        "title_en": "Pro",
    }
    assert markets["international"]["credit_packs"][0] == {
        "code": "credits_250",
        "price_minor": 499,
        "credits": 250,
    }

    quote = api_client.post(
        "/api/v1/pricing/quote",
        json={"action_type": "split_model", "quantity": 3},
        headers=actor.headers,
    )
    assert quote.status_code == 200, quote.text
    assert quote.json() == {
        "version": "2026-10-29.v2",
        "charging_mode": "shadow",
        "action_type": "split_model",
        "quantity": 3,
        "unit_credits": "6",
        "total_credits": "18",
    }


def test_unknown_action_and_invalid_quantity_fail_closed(
    api_client: TestClient, actor: Actor
) -> None:
    unknown = api_client.post(
        "/api/v1/pricing/quote",
        json={"action_type": "not_registered", "quantity": 1},
        headers=actor.headers,
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "validation_failed"

    invalid = api_client.post(
        "/api/v1/pricing/quote",
        json={"action_type": "slice", "quantity": 0},
        headers=actor.headers,
    )
    assert invalid.status_code == 422
