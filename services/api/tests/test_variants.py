"""T-135 (F-075): one request, several constructive answers — deterministic in the stub."""

from __future__ import annotations

import pytest

from app.ai.contract import PlanRequest, Variant, user_message
from app.ai.planner import StubPlanner, plan_with_repair


def planned(prompt: str, strategy: str, **request: object) -> list[dict[str, object]]:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(prompt=prompt, variant=Variant(index=1, of=3, strategy=strategy), **request),
    )
    assert outcome.status == "planned", outcome
    assert outcome.plan is not None
    return [op.model_dump() for op in outcome.plan.operations]


def test_as_described_is_the_plain_plan() -> None:
    plain = plan_with_repair(StubPlanner(), PlanRequest(prompt="Box 40x20x8 mm")).plan
    assert plain is not None
    variant = planned("Box 40x20x8 mm", "as_described")
    assert [op["type"] for op in variant] == [op.type for op in plain.operations]


def test_rounded_adds_a_fillet_scaled_to_the_part() -> None:
    ops = planned("Box 40x20x8 mm", "rounded")
    assert [op["type"] for op in ops] == ["create_box", "fillet"]
    assert ops[-1]["radius_mm"] == pytest.approx(1.2)  # 15 % of the 8 mm height, capped at 2
    big = planned("Box 100x100x50 mm", "rounded")
    assert big[-1]["radius_mm"] == 2.0


def test_rounded_does_not_double_a_fillet_the_user_asked_for() -> None:
    ops = planned("Box 40x20x8 mm, fillet 3 mm", "rounded")
    assert [op["type"] for op in ops].count("fillet") == 1
    assert ops[-1]["radius_mm"] == 3


@pytest.mark.parametrize(
    ("strategy", "height"),
    [("sturdier", 10.0), ("lower_profile", 6.4)],
)
def test_profile_variants_change_only_the_height(strategy: str, height: float) -> None:
    ops = planned("Box 40x20x8 mm", strategy)
    assert [op["type"] for op in ops] == ["create_box", "set_parameter"]
    assert ops[-1]["operation"] == "body" and ops[-1]["parameter"] == "height_mm"
    assert ops[-1]["value"] == pytest.approx(height)


def test_variants_work_on_organizers_and_cylinders_too() -> None:
    organizer = planned("Органайзер 200×100×50 мм с 6 секциями", "sturdier")
    assert organizer[-1]["type"] == "set_parameter" and organizer[-1]["value"] == 62.5
    puck = planned("Cylinder diameter 40 mm, height 20 mm", "rounded")
    assert puck[-1]["type"] == "fillet" and puck[-1]["radius_mm"] == 2.0


def test_the_provider_prompt_names_the_variant() -> None:
    request = PlanRequest(prompt="a bracket", variant=Variant(index=2, of=3, strategy="sturdier"))
    assert "Variant 2 of 3: Sturdier: thicker base" in user_message(request)
