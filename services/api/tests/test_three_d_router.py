"""The 3D provider router keeps budget, latency and privacy promises."""

from decimal import Decimal

import pytest

from app.ai.providers.shap_e_3d import ShapEThreeDProvider
from app.ai.three_d import GenerationEstimate, GenerationRequest
from app.ai.three_d_router import (
    ProviderRoute,
    ProviderRoutingEvidence,
    select_provider,
)
from app.api.errors import ValidationFailedError


class PricedShapE(ShapEThreeDProvider):
    def __init__(self, name: str, cost: str, latency: int) -> None:
        self.name = name
        self._cost = Decimal(cost)
        self._latency = latency

    def estimate(self, request: GenerationRequest) -> GenerationEstimate:
        return (
            super()
            .estimate(request)
            .model_copy(
                update={
                    "provider": self.name,
                    "cost_usd": self._cost,
                    "latency_seconds_max": self._latency,
                }
            )
        )


def request(**overrides: object) -> GenerationRequest:
    values: dict[str, object] = {
        "mode": "text",
        "purpose": "draft",
        "prompt": "an owl figurine",
        "target_format": "glb",
    }
    values.update(overrides)
    return GenerationRequest.model_validate(values)


def test_router_uses_server_side_priority_then_cost_and_latency() -> None:
    slower = PricedShapE("slower", "0.10", 600)
    faster = PricedShapE("faster", "0.05", 300)
    decision = select_provider(
        [
            ProviderRoute(provider=slower, default_priority=20),
            ProviderRoute(provider=faster, default_priority=20),
        ],
        request(),
    )

    assert decision.provider.name == "faster"
    assert decision.estimate.cost_usd == Decimal("0.05")


def test_router_learns_only_between_equal_priority_routes_with_complete_evidence() -> None:
    cheaper = PricedShapE("cheaper", "0.05", 200)
    preferred = PricedShapE("preferred", "0.10", 300)
    routes = [
        ProviderRoute(provider=cheaper, default_priority=20),
        ProviderRoute(provider=preferred, default_priority=20),
    ]
    evidence = {
        ("cheaper", "text300M"): ProviderRoutingEvidence(10, 4),
        ("preferred", "text300M"): ProviderRoutingEvidence(10, 8),
    }

    assert select_provider(routes, request(), evidence).provider.name == "preferred"

    incomplete = {("preferred", "text300M"): ProviderRoutingEvidence(10, 8)}
    assert select_provider(routes, request(), incomplete).provider.name == "cheaper"

    sparse = {
        ("cheaper", "text300M"): ProviderRoutingEvidence(4, 1),
        ("preferred", "text300M"): ProviderRoutingEvidence(4, 4),
    }
    assert select_provider(routes, request(), sparse).provider.name == "cheaper"

    higher_priority = [
        ProviderRoute(provider=cheaper, default_priority=10),
        ProviderRoute(provider=preferred, default_priority=20),
    ]
    assert select_provider(higher_priority, request(), evidence).provider.name == "cheaper"


def test_router_fails_closed_for_budget_latency_and_unknown_cost() -> None:
    with pytest.raises(ValidationFailedError) as budget:
        select_provider(
            [ProviderRoute(provider=PricedShapE("paid", "0.50", 300))],
            request(budget_usd="0.25"),
        )
    assert budget.value.details["reasons"] == ["budget_exceeded"]

    with pytest.raises(ValidationFailedError) as latency:
        select_provider(
            [ProviderRoute(provider=PricedShapE("slow", "0.10", 300))],
            request(max_latency_seconds=120),
        )
    assert latency.value.details["reasons"] == ["latency_limit_exceeded"]

    with pytest.raises(ValidationFailedError) as unknown:
        select_provider(
            [ProviderRoute(provider=ShapEThreeDProvider())],
            request(budget_usd="1.00"),
        )
    assert unknown.value.details["reasons"] == ["provider_cost_unknown"]


def test_single_provider_keeps_its_precise_capability_error() -> None:
    with pytest.raises(ValidationFailedError) as unsupported:
        select_provider(
            [ProviderRoute(provider=ShapEThreeDProvider())],
            request(purpose="game", pbr=True),
        )
    assert set(unsupported.value.details["unsupported"]) == {"purpose=game", "pbr=true"}


def test_external_personal_data_retention_and_training_need_separate_consent() -> None:
    route = ProviderRoute(
        provider=PricedShapE("external", "0.10", 300),
        external_processing=True,
        retains_inputs=True,
        trains_on_inputs=True,
    )
    private = request(privacy={"contains_personal_data": True})

    with pytest.raises(ValidationFailedError) as denied:
        select_provider([route], private)
    assert denied.value.details["reasons"] == [
        "external_processing_consent_required",
        "provider_retention_consent_required",
        "provider_training_consent_required",
    ]

    allowed = request(
        privacy={
            "contains_personal_data": True,
            "allow_external_processing": True,
            "allow_provider_retention": True,
            "allow_training": True,
        }
    )
    assert select_provider([route], allowed).provider.name == "external"
