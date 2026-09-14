"""Planner façade (T-043): provider selection, one repair round, strict validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.ai import validator
from app.ai.contract import PlannerOutput, PlannerResult, PlanRequest, Usage
from app.ai.providers import stub
from app.config import Settings
from app.geometry.operations import OperationPlan


class Planner(Protocol):
    def plan(self, request: PlanRequest) -> PlannerResult: ...


class StubPlanner:
    def plan(self, request: PlanRequest) -> PlannerResult:
        return stub.plan(request)


def planner_for(settings: Settings) -> Planner:
    if settings.ai_provider == "anthropic":
        from app.ai.providers.anthropic_provider import AnthropicPlanner

        return AnthropicPlanner(
            model=settings.ai_model, effort=settings.ai_effort, api_key=settings.anthropic_api_key
        )
    return StubPlanner()


@dataclass(slots=True)
class PlanningOutcome:
    """What one planning attempt (plus at most one repair round) produced."""

    status: str  # planned | needs_clarification | rejected | refused
    plan: OperationPlan | None = None
    clarifications: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    refusal: str | None = None
    attempts: list[PlannerResult] = field(default_factory=list)

    @property
    def usage(self) -> list[Usage]:
        return [attempt.usage for attempt in self.attempts]

    @property
    def cost_usd(self) -> Decimal:
        return sum((u.cost_usd for u in self.usage), Decimal("0"))

    @property
    def raw_output(self) -> PlannerOutput | None:
        return self.attempts[-1].output if self.attempts else None


def plan_with_repair(planner: Planner, request: PlanRequest) -> PlanningOutcome:
    """Ask once; if the output is structurally fine but invalid, ask once more with the
    validator's messages attached (docs/07: unsupported op -> clarification/refusal)."""
    outcome = PlanningOutcome(status="rejected")
    first = planner.plan(request)
    outcome.attempts.append(first)
    verdict = _judge(first, outcome)
    if verdict is not None:
        return verdict

    repair_request = request.model_copy(
        update={
            "conversation": [
                *request.conversation,
                {
                    "question": "Your previous plan was rejected by the validator: "
                    + "; ".join(outcome.errors)
                    + ". Return a corrected plan or ask for clarification.",
                    "answer": "",
                },
            ]
        }
    )
    second = planner.plan(repair_request)
    outcome.attempts.append(second)
    verdict = _judge(second, outcome)
    return verdict or outcome


def _judge(result: PlannerResult, outcome: PlanningOutcome) -> PlanningOutcome | None:
    if result.refusal:
        outcome.status = "refused"
        outcome.refusal = result.refusal
        return outcome
    if result.output is None:
        outcome.status = "rejected"
        outcome.errors = ["planner returned no output"]
        return outcome
    checked = validator.validate_output(result.output)
    if checked.ok and checked.plan is not None:
        if checked.plan.needs_clarification:
            outcome.status = "needs_clarification"
            outcome.plan = checked.plan
            outcome.clarifications = list(checked.plan.required_clarifications)
        else:
            outcome.status = "planned"
            outcome.plan = checked.plan
        outcome.errors = []
        return outcome
    outcome.status = "rejected"
    outcome.errors = checked.errors
    return None  # give the provider one repair round
