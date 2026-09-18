"""T-093: a prompt corpus that must keep producing valid plans.

Every case states the outcome a user would recognise — a plan with these operations, or a
question instead of a guess — and the plan is validated against the live operation
registry. A planner change that starts inventing operations, dropping dimensions or
answering a question it should have asked fails here.

The corpus is the fixture file `prompt_corpus.json`; the stub planner runs offline, so
this suite costs nothing and runs on every commit. Provider planners are exercised
against the same corpus in a paid job, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.contract import PlanRequest
from app.ai.planner import StubPlanner, plan_with_repair
from app.geometry.operations import OPERATION_TYPES, parse_plan

CORPUS = Path(__file__).with_name("prompt_corpus.json")


def cases() -> list[dict[str, Any]]:
    corpus: list[dict[str, Any]] = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
    return corpus


def ids() -> list[str]:
    return [case["id"] for case in cases()]


@pytest.mark.parametrize("case", cases(), ids=ids())
def test_prompt_produces_the_expected_outcome(case: dict[str, Any]) -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt=case["prompt"],
            current_operations=case.get("current_operations", []),
            selection_entity_ids=case.get("selection", []),
            conversation=case.get("conversation", []),
        ),
    )
    assert outcome.status == case["expect"], (
        f"{case['id']}: {outcome.errors or outcome.clarifications}"
    )

    if case["expect"] == "planned":
        assert outcome.plan is not None
        types = [op.type for op in outcome.plan.operations]
        assert types == case["operations"], case["id"]
        # The plan must survive a strict re-parse: what the kernel will be handed.
        parse_plan(outcome.plan.model_dump(mode="json"))
        for key, value in case.get("first_operation", {}).items():
            assert outcome.plan.operations[0].model_dump()[key] == pytest.approx(value), key
    else:
        assert outcome.clarifications, case["id"]
        for fragment in case.get("asks_about", []):
            assert any(fragment.lower() in q.lower() for q in outcome.clarifications), (
                f"{case['id']}: expected a question mentioning {fragment!r}, "
                f"got {outcome.clarifications}"
            )


def test_every_operation_type_the_corpus_uses_is_in_the_registry() -> None:
    used = {op for case in cases() for op in case.get("operations", [])}
    assert used <= set(OPERATION_TYPES), (
        f"corpus uses unknown operations: {used - set(OPERATION_TYPES)}"
    )


def test_the_corpus_covers_both_languages_and_both_outcomes() -> None:
    corpus = cases()
    assert any(case["expect"] == "planned" for case in corpus)
    assert any(case["expect"] == "needs_clarification" for case in corpus)
    assert any(case.get("language") == "ru" for case in corpus)
    assert any(case.get("language") == "en" for case in corpus)
    assert len({case["id"] for case in corpus}) == len(corpus), "duplicate case ids"
