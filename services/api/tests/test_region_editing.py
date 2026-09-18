"""E13 (F-062/F-003): outline an area, say what belongs there, and nothing else moves."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai import validator
from app.ai.contract import PlannerOutput, PlanRequest, user_message
from app.ai.planner import StubPlanner, plan_with_repair
from app.geometry.region import BoxRegion, LassoRegion, RegionSelection, parse_region

PLATE = [
    {
        "id": "body",
        "type": "create_box",
        "schema_version": 1,
        "width_mm": 60,
        "depth_mm": 40,
        "height_mm": 8,
    }
]


def outline(**overrides: Any) -> dict[str, Any]:
    """A rectangle drawn on the top face of the plate, through its full thickness."""
    payload: dict[str, Any] = {
        "region": {
            "kind": "lasso",
            "axis": "z",
            "offset_mm": 8,
            "depth_mm": 16,
            "points_mm": [[20, 12], [40, 12], [40, 28], [20, 28]],
        },
        "target": "body",
        "surface_axis": "z",
        "surface_sign": "+",
    }
    payload.update(overrides)
    return payload


# --- T-101 the contract ------------------------------------------------------------------


def test_a_lasso_becomes_the_volume_it_sweeps() -> None:
    region = parse_region(outline())
    box = region.bounds()
    assert box.min_mm == (20.0, 12.0, 0.0)
    assert box.max_mm == (40.0, 28.0, 16.0)
    assert box.size_mm == (20.0, 16.0, 16.0)
    assert box.centre_mm == (30.0, 20.0, 8.0)
    assert region.surface_mm == 8.0  # the face the outline was drawn on


def test_a_region_with_no_area_is_refused() -> None:
    with pytest.raises(ValueError, match="no area"):
        LassoRegion(axis="z", offset_mm=0, points_mm=[[1, 1], [1, 2], [1, 3]])
    with pytest.raises(ValueError, match="greater than"):
        BoxRegion(min_mm=(0, 0, 0), max_mm=(0, 10, 10))


def test_the_region_is_described_for_the_planner_in_millimetres() -> None:
    text = parse_region(outline()).describe()
    assert "20.0 x 16.0 x 16.0 mm" in text
    assert "centred at (30.0, 20.0, 8.0) mm" in text
    assert "+z face" in text and "'body'" in text

    message = user_message(PlanRequest(prompt="a hole here", region=parse_region(outline())))
    assert "outlined a region" in message


# --- T-104 planning inside the region ------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Сделай тут отверстие 6 мм", ["add_hole"]),
        ("drill a 5 mm hole here", ["add_hole"]),
        ("add a pocket 3 mm deep here", ["create_box", "boolean"]),
        ("карман глубиной 2 мм", ["create_box", "boolean"]),
        ("raise a 2 mm pad here", ["create_box", "boolean"]),
        ("нарасти выступ 2 мм", ["create_box", "boolean"]),
    ],
)
def test_region_prompts_produce_in_region_operations(prompt: str, expected: list[str]) -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(prompt=prompt, current_operations=PLATE, region=parse_region(outline())),
    )
    assert outcome.status == "planned", outcome.errors or outcome.clarifications
    assert outcome.plan is not None
    added = outcome.plan.operations[len(PLATE) :]
    assert [op.type for op in added] == expected
    # And the plan replays the model first: the rest of the part is untouched.
    assert [op.type for op in outcome.plan.operations[: len(PLATE)]] == ["create_box"]


def test_a_pocket_starts_at_the_surface_the_user_drew_on() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="pocket 3 mm deep here", current_operations=PLATE, region=parse_region(outline())
        ),
    )
    assert outcome.plan is not None
    tool = outcome.plan.operations[-2].model_dump()
    assert tool["height_mm"] == pytest.approx(3.0)
    assert tool["origin_mm"][2] == pytest.approx(5.0)  # 8 mm surface, 3 mm down
    assert outcome.plan.operations[-1].model_dump()["op"] == "cut"


def test_a_pad_grows_outwards_from_the_surface() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="boss 2 mm tall here", current_operations=PLATE, region=parse_region(outline())
        ),
    )
    assert outcome.plan is not None
    tool = outcome.plan.operations[-2].model_dump()
    assert tool["origin_mm"][2] == pytest.approx(8.0)
    assert outcome.plan.operations[-1].model_dump()["op"] == "fuse"


def test_a_vague_region_prompt_asks_what_to_do_there() -> None:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="сделай тут красиво", current_operations=PLATE, region=parse_region(outline())
        ),
    )
    assert outcome.status == "needs_clarification"
    assert any("области" in question for question in outcome.clarifications)


def test_outlining_before_there_is_a_model_says_so() -> None:
    outcome = plan_with_repair(
        StubPlanner(), PlanRequest(prompt="a hole here", region=parse_region(outline()))
    )
    assert outcome.status == "needs_clarification"
    assert any("model" in q or "модель" in q for q in outcome.clarifications)


# --- T-103 the region is enforced ----------------------------------------------------------


def region_plan(*operations: dict[str, Any]) -> PlannerOutput:
    return PlannerOutput(goal="region edit", operations=[*PLATE, *operations])


def check(plan: PlannerOutput, region: RegionSelection | None) -> validator.ValidationOutcome:
    return validator.validate_output(plan, base_operations=PLATE, region=region)


def test_geometry_outside_the_outline_is_rejected() -> None:
    far_away = {
        "id": "elsewhere",
        "type": "create_box",
        "schema_version": 1,
        "width_mm": 5,
        "depth_mm": 5,
        "height_mm": 5,
        "origin_mm": [0, 0, 0],  # the region starts at x=20, y=12
    }
    outcome = check(region_plan(far_away), parse_region(outline()))
    assert not outcome.ok
    assert "outside the region" in outcome.errors[0]


def test_a_hole_outside_the_outline_is_rejected() -> None:
    hole = {
        "id": "stray",
        "type": "add_hole",
        "schema_version": 1,
        "target": "body",
        "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
        "position_mm": [55, 35],  # the outline covers x 20..40, y 12..28
        "diameter_mm": 4,
    }
    outcome = check(region_plan(hole), parse_region(outline()))
    assert not outcome.ok
    assert "outside the region" in outcome.errors[0]


def test_geometry_inside_the_outline_passes() -> None:
    inside = {
        "id": "pad",
        "type": "create_box",
        "schema_version": 1,
        "width_mm": 10,
        "depth_mm": 10,
        "height_mm": 2,
        "origin_mm": [25, 15, 8],
    }
    assert check(region_plan(inside), parse_region(outline())).ok


def test_replaying_the_model_is_not_a_region_violation() -> None:
    """The history covers the whole part; only what the plan adds is held to the outline."""
    assert check(region_plan(), parse_region(outline())).ok


def test_without_an_outline_nothing_is_restricted() -> None:
    anywhere = {
        "id": "elsewhere",
        "type": "create_box",
        "schema_version": 1,
        "width_mm": 5,
        "depth_mm": 5,
        "height_mm": 5,
        "origin_mm": [0, 0, 0],
    }
    assert check(region_plan(anywhere), None).ok
