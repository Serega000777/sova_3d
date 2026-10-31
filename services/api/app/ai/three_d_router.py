"""Fail-closed rule-based routing for provider-neutral 3D generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.ai.three_d import (
    GenerationEstimate,
    GenerationPurpose,
    GenerationRequest,
    ThreeDProvider,
)
from app.api.errors import ValidationFailedError


@dataclass(frozen=True)
class ProviderRoute:
    provider: ThreeDProvider
    default_priority: int = 100
    purpose_priority: dict[GenerationPurpose, int] = field(default_factory=dict)
    external_processing: bool = False
    retains_inputs: bool = False
    trains_on_inputs: bool = False

    def priority_for(self, purpose: GenerationPurpose) -> int:
        return self.purpose_priority.get(purpose, self.default_priority)


@dataclass(frozen=True)
class RoutingDecision:
    provider: ThreeDProvider
    estimate: GenerationEstimate


@dataclass(frozen=True)
class ProviderRoutingEvidence:
    """Observed human outcomes for one provider/model and one mode/purpose lane."""

    rated_outcomes: int
    accepted_outcomes: int

    @property
    def acceptance_rate(self) -> Decimal:
        if self.rated_outcomes <= 0:
            return Decimal(0)
        return Decimal(self.accepted_outcomes) / Decimal(self.rated_outcomes)


MIN_LEARNED_OUTCOMES = 5


def _policy_rejections(route: ProviderRoute, request: GenerationRequest) -> list[str]:
    privacy = request.privacy
    rejected: list[str] = []
    if (
        privacy.contains_personal_data
        and route.external_processing
        and not privacy.allow_external_processing
    ):
        rejected.append("external_processing_consent_required")
    if route.retains_inputs and not privacy.allow_provider_retention:
        rejected.append("provider_retention_consent_required")
    if route.trains_on_inputs and not privacy.allow_training:
        rejected.append("provider_training_consent_required")
    return rejected


def select_provider(
    routes: list[ProviderRoute],
    request: GenerationRequest,
    evidence: Mapping[tuple[str, str], ProviderRoutingEvidence] | None = None,
) -> RoutingDecision:
    """Select one capable route without weakening policy or learning from sparse evidence."""

    eligible: list[tuple[int, RoutingDecision, ProviderRoutingEvidence | None]] = []
    rejection_reasons: set[str] = set()
    capability_errors: list[ValidationFailedError] = []
    for route in routes:
        policy_rejections = _policy_rejections(route, request)
        if policy_rejections:
            rejection_reasons.update(policy_rejections)
            continue
        try:
            estimate = route.provider.estimate(request)
        except ValidationFailedError as exc:
            capability_errors.append(exc)
            continue
        if request.budget_usd is not None:
            if estimate.cost_usd is None:
                rejection_reasons.add("provider_cost_unknown")
                continue
            if estimate.cost_usd > request.budget_usd:
                rejection_reasons.add("budget_exceeded")
                continue
        if (
            request.max_latency_seconds is not None
            and estimate.latency_seconds_max > request.max_latency_seconds
        ):
            rejection_reasons.add("latency_limit_exceeded")
            continue
        eligible.append(
            (
                route.priority_for(request.purpose),
                RoutingDecision(provider=route.provider, estimate=estimate),
                (evidence or {}).get((route.provider.name, estimate.model)),
            )
        )
    if not eligible:
        if len(routes) == 1 and len(capability_errors) == 1 and not rejection_reasons:
            raise capability_errors[0]
        if capability_errors:
            rejection_reasons.add("unsupported_capabilities")
        raise ValidationFailedError(
            "no 3D provider satisfies the request constraints",
            {"reasons": sorted(rejection_reasons) or ["no_provider_configured"]},
        )
    best_priority = min(item[0] for item in eligible)
    priority_candidates = [item for item in eligible if item[0] == best_priority]
    use_learned_rank = len(priority_candidates) > 1 and all(
        item[2] is not None and item[2].rated_outcomes >= MIN_LEARNED_OUTCOMES
        for item in priority_candidates
    )

    def rank(
        item: tuple[int, RoutingDecision, ProviderRoutingEvidence | None],
    ) -> tuple[Decimal, bool, Decimal, int, str]:
        decision = item[1]
        observed = item[2]
        learned = Decimal(0)
        if use_learned_rank and observed is not None:
            learned = -observed.acceptance_rate
        cost = (
            decision.estimate.cost_usd
            if decision.estimate.cost_usd is not None
            else Decimal("Infinity")
        )
        return (
            learned,
            decision.estimate.cost_usd is None,
            cost,
            decision.estimate.latency_seconds_max,
            decision.provider.name,
        )

    priority_candidates.sort(key=rank)
    return priority_candidates[0][1]
