"""T-041 contract, T-043 prompt fixtures (RU/EN), T-044 validator, repair round, cost math."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai import validator
from app.ai.contract import PlannerOutput, PlannerResult, PlanRequest, Usage, system_prompt
from app.ai.planner import PlanningOutcome, StubPlanner, plan_with_repair
from app.ai.providers import stub
from app.ai.providers.anthropic_provider import estimate_cost
from app.geometry.operations import OPERATION_TYPES

# --- T-041 -----------------------------------------------------------------------------------


def test_system_prompt_is_stable_and_lists_every_operation() -> None:
    prompt = system_prompt()
    assert prompt == system_prompt()  # cacheable: no timestamps, ids or randomness
    for op_type in OPERATION_TYPES:
        assert f"- {op_type}:" in prompt
    assert "millimetres" in prompt and "required_clarifications" in prompt
    assert "face_by_normal" in prompt and "set_parameter" in prompt


# --- T-043: prompt -> plan fixtures ---------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected_types", "bbox"),
    [
        ("Box 40x20x8 mm", ["create_box"], (40, 20, 8)),
        ("коробка 40х20х8 мм", ["create_box"], (40, 20, 8)),
        ("Make a plate 10 x 5 x 1 cm", ["create_box"], (100, 50, 10)),
        ('bracket 2" x 1" x 0.25"', ["create_box"], (50.8, 25.4, 6.35)),
    ],
)
def test_box_prompts_in_both_languages(
    prompt: str, expected_types: list[str], bbox: tuple[float, float, float]
) -> None:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt))
    assert outcome.status == "planned", outcome
    assert outcome.plan is not None
    assert [op.type for op in outcome.plan.operations] == expected_types
    box = outcome.plan.operations[0].model_dump()
    assert (box["width_mm"], box["depth_mm"], box["height_mm"]) == pytest.approx(bbox)
    assert any(
        "millimetre" in a.lower() or "миллиметр" in a.lower() for a in outcome.plan.assumptions
    )


def test_organizer_prompt_ru_produces_compartments_and_walls() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(prompt="Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм"),
    )
    assert outcome.status == "planned" and outcome.plan is not None
    types = [op.type for op in outcome.plan.operations]
    assert types.count("boolean") == 6 and types.count("create_box") == 7
    assert types[-1] == "fillet"
    pockets = [op for op in outcome.plan.operations if op.id.startswith("pocket_")]
    first = pockets[0].model_dump()
    assert first["origin_mm"] == (2.0, 2.0, 3.0)  # 2 mm wall, 3 mm floor
    assert first["height_mm"] == 47.0
    assert all(p.model_dump()["width_mm"] == pytest.approx(64.0) for p in pockets)  # 3x2 grid
    assert any("стенк" in a.lower() for a in outcome.plan.assumptions)
    assert "6 compartments" in " ".join(outcome.plan.validation_steps)


def test_holes_and_cylinder_prompts() -> None:
    holes = plan_with_repair(
        StubPlanner(), PlanRequest(prompt="Plate 60x20x8 mm with 2 holes 5.5 mm")
    )
    assert holes.plan is not None
    hole_ops = [op for op in holes.plan.operations if op.type == "add_hole"]
    assert len(hole_ops) == 2
    positions = [op.model_dump()["position_mm"] for op in hole_ops]
    assert positions == [(20.0, 10.0), (40.0, 10.0)]

    cyl = plan_with_repair(StubPlanner(), PlanRequest(prompt="цилиндр диаметр 40 мм высота 20 мм"))
    assert cyl.plan is not None and cyl.plan.operations[0].type == "create_cylinder"


# --- T-042 clarification state (planner side) ---------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "fragment"),
    [
        ("сделай коробку для ключей", "Ш×Г×В"),
        ("make me a box", "W×D×H"),
        ("box 40x20 mm", "height"),
        ("cylinder for a pipe", "diameter and height"),
    ],
)
def test_missing_dimensions_ask_instead_of_guessing(prompt: str, fragment: str) -> None:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt))
    assert outcome.status == "needs_clarification"
    assert outcome.plan is not None and outcome.plan.operations == []
    assert any(fragment in q for q in outcome.clarifications), outcome.clarifications


def test_answer_to_clarification_completes_the_plan() -> None:
    request = PlanRequest(
        prompt="make me a box",
        conversation=[{"question": "Please give the size as W×D×H in mm", "answer": "30x20x10 mm"}],
    )
    outcome = plan_with_repair(StubPlanner(), request)
    assert outcome.status == "planned" and outcome.plan is not None
    assert outcome.plan.operations[0].model_dump()["width_mm"] == 30.0


def test_unsupported_shape_is_a_clarification_not_an_invented_operation() -> None:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt="Статуэтка дракона 10 см"))
    assert outcome.status == "needs_clarification"
    assert outcome.plan is not None and outcome.plan.operations == []
    assert "параметрические" in outcome.clarifications[0]


# --- T-044 validator ----------------------------------------------------------------------


def test_validator_rejects_unknown_operation_types() -> None:
    out = validator.validate_output(
        {
            "goal": "x",
            "operations": [{"id": "s", "type": "create_helix", "schema_version": 1, "r": 1}],
        }
    )
    assert not out.ok and out.rejected_types == ["create_helix"]
    assert "unsupported type 'create_helix'" in out.errors[0]
    assert "create_box" in out.errors[0]  # tells the planner what is allowed


def test_validator_reports_semantic_errors_with_locations() -> None:
    out = validator.validate_output(
        {
            "goal": "x",
            "operations": [
                {
                    "id": "b",
                    "type": "create_box",
                    "schema_version": 1,
                    "width_mm": 0,
                    "depth_mm": 1,
                    "height_mm": 1,
                },
                {
                    "id": "c",
                    "type": "boolean",
                    "schema_version": 1,
                    "op": "cut",
                    "target": "b",
                    "tool": "ghost",
                },
            ],
        }
    )
    assert not out.ok
    assert any("width_mm" in e for e in out.errors)


def test_validator_forbids_operations_alongside_clarifications() -> None:
    out = validator.validate_output(
        {
            "goal": "x",
            "required_clarifications": ["which size?"],
            "operations": [
                {
                    "id": "b",
                    "type": "create_box",
                    "schema_version": 1,
                    "width_mm": 1,
                    "depth_mm": 1,
                    "height_mm": 1,
                }
            ],
        }
    )
    assert not out.ok and "required_clarifications must be empty" in out.errors[0]


def test_validator_accepts_a_clean_plan() -> None:
    out = validator.validate_output(
        PlannerOutput(
            goal="box",
            operations=[
                {
                    "id": "b",
                    "type": "create_box",
                    "schema_version": 1,
                    "width_mm": 10,
                    "depth_mm": 10,
                    "height_mm": 10,
                }
            ],
        )
    )
    assert out.ok and out.plan is not None and out.plan.operations[0].id == "b"


# --- repair round + refusal ------------------------------------------------------------------


class ScriptedPlanner:
    """Returns the queued outputs in order and records what it was asked."""

    def __init__(self, outputs: list[PlannerOutput | None], refusal: str | None = None) -> None:
        self.outputs = outputs
        self.refusal = refusal
        self.requests: list[PlanRequest] = []

    def plan(self, request: PlanRequest) -> PlannerResult:
        self.requests.append(request)
        output = self.outputs.pop(0) if self.outputs else None
        return PlannerResult(
            output=output,
            raw_text="",
            usage=Usage(provider="scripted", model="m", cost_usd=Decimal("0.01")),
            refusal=self.refusal,
        )


def test_invalid_output_gets_one_repair_round_with_validator_feedback() -> None:
    bad = PlannerOutput(
        goal="x", operations=[{"id": "s", "type": "create_sphere", "schema_version": 1}]
    )
    good = PlannerOutput(
        goal="x",
        operations=[
            {
                "id": "b",
                "type": "create_box",
                "schema_version": 1,
                "width_mm": 5,
                "depth_mm": 5,
                "height_mm": 5,
            }
        ],
    )
    planner = ScriptedPlanner([bad, good])
    outcome = plan_with_repair(planner, PlanRequest(prompt="ball"))
    assert outcome.status == "planned" and len(outcome.attempts) == 2
    assert "create_sphere" in planner.requests[1].conversation[-1]["question"]
    assert outcome.cost_usd == Decimal("0.02")


def test_still_invalid_after_repair_is_rejected() -> None:
    bad = PlannerOutput(goal="x", operations=[{"id": "s", "type": "nope", "schema_version": 1}])
    outcome = plan_with_repair(ScriptedPlanner([bad, bad]), PlanRequest(prompt="x"))
    assert outcome.status == "rejected" and outcome.errors and outcome.plan is None


def test_provider_refusal_short_circuits() -> None:
    outcome = plan_with_repair(ScriptedPlanner([None], refusal="declined"), PlanRequest(prompt="x"))
    assert outcome.status == "refused" and outcome.refusal == "declined"
    assert len(outcome.attempts) == 1


# --- T-046 cost math -----------------------------------------------------------------------


def test_estimate_cost_uses_public_rates_and_cache_discount() -> None:
    assert estimate_cost("claude-opus-5", 1_000_000, 0, 0) == Decimal("5.000000")
    assert estimate_cost("claude-opus-5", 0, 1_000_000, 0) == Decimal("25.000000")
    assert estimate_cost("claude-opus-5", 1_000_000, 0, 1_000_000) == Decimal("0.500000")
    assert estimate_cost("claude-sonnet-5", 2_000, 500, 0) == Decimal("0.009000")
    assert estimate_cost("unknown-model", 1_000_000, 0, 0) == Decimal("5.000000")


def test_stub_usage_is_free() -> None:
    result = stub.plan(PlanRequest(prompt="Box 1x1x1 mm"))
    assert result.usage.cost_usd == 0 and result.usage.provider == "stub"
    assert isinstance(PlanningOutcome(status="planned").cost_usd, Decimal)


# --- T-050/T-051: editing an existing model inside the selection -----------------------------


def box_history(width: float = 40, depth: float = 20, height: float = 8) -> list[dict[str, object]]:
    return [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": width,
            "depth_mm": depth,
            "height_mm": height,
        }
    ]


def test_edit_replays_the_history_and_appends_the_change() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="Скругли рёбра на 2 мм",
            current_operations=box_history(),
            selection_entity_ids=["body"],
        ),
    )
    assert outcome.status == "planned", outcome
    assert outcome.plan is not None
    types = [op.type for op in outcome.plan.operations]
    assert types == ["create_box", "fillet"]
    fillet = outcome.plan.operations[-1].model_dump()
    assert fillet["target"] == "body" and fillet["radius_mm"] == 2
    assert outcome.plan.expected_outputs == ["body"]


def test_edit_can_resize_and_drill_the_selected_body() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="Сделай 80×20×25 мм и отверстие 5 мм",
            current_operations=box_history(),
            selection_entity_ids=["body"],
        ),
    )
    assert outcome.status == "planned" and outcome.plan is not None
    assert [op.type for op in outcome.plan.operations] == [
        "create_box",
        "set_dimensions",
        "add_hole",
    ]
    resize = outcome.plan.operations[1].model_dump()
    assert (resize["width_mm"], resize["depth_mm"], resize["height_mm"]) == (80, 20, 25)


def test_edit_without_a_recognizable_change_asks_instead_of_guessing() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(prompt="Сделай красивее", current_operations=box_history()),
    )
    assert outcome.status == "needs_clarification"
    assert any("изменить" in question for question in outcome.clarifications)


def test_scope_violation_is_rejected_when_a_selection_is_active() -> None:
    base = [
        *box_history(),
        {
            "id": "lid",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 40,
            "depth_mm": 20,
            "height_mm": 2,
        },
    ]
    off_scope = PlannerOutput(
        goal="round the lid",
        operations=[
            *base,
            {
                "id": "soften",
                "type": "fillet",
                "schema_version": 1,
                "target": "lid",  # the user selected "body", not "lid"
                "edges": {"kind": "edges_parallel_to", "axis": "z"},
                "radius_mm": 1,
            },
        ],
    )
    checked = validator.validate_output(off_scope, scope=["body"], base_operations=base)
    assert not checked.ok
    assert "outside the selection" in checked.errors[0]


def test_rewriting_an_unselected_operation_is_a_scope_violation() -> None:
    base = box_history()
    rewritten = PlannerOutput(
        goal="quietly resize",
        operations=[{**base[0], "width_mm": 400}],
    )
    checked = validator.validate_output(rewritten, scope=["lid"], base_operations=base)
    assert not checked.ok
    assert "parameters changed" in checked.errors[0]


def test_no_selection_means_no_scope_restriction() -> None:
    base = box_history()
    plan = PlannerOutput(goal="resize", operations=[{**base[0], "width_mm": 400}])
    assert validator.validate_output(plan, base_operations=base).ok
