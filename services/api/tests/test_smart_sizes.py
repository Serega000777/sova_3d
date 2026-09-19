"""T-120/T-121 (F-025): sizes that mean something — screws, pipes, phones, tolerances."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai import smart_sizes
from app.ai.contract import PlanRequest
from app.ai.planner import StubPlanner, plan_with_repair


def planned(prompt: str, **request: Any) -> Any:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt, **request))
    assert outcome.status == "planned", outcome
    assert outcome.plan is not None
    return outcome.plan


def asks(prompt: str, **request: Any) -> list[str]:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt, **request))
    assert outcome.status == "needs_clarification", outcome
    return outcome.clarifications


def box_history() -> list[dict[str, Any]]:
    return [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 8,
        }
    ]


# --- screws --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "diameter"),
    [
        ("Plate 60x40x8 mm with 2 holes for M5", 5.7),  # 5.5 clearance + 0.2 PLA undersize
        ("Пластина 60×40×8 мм, два отверстия под М3", 3.6),
        ("Plate 60x40x8 mm, holes for M3 heat-set inserts", 4.2),
        ("Пластина 60×40×8 мм с отверстием под саморез M3", 2.9),
        ("Plate 60x40x8 mm with M4 holes, PETG", 4.8),  # PETG closes holes more
    ],
)
def test_a_screw_size_is_a_hole_size(prompt: str, diameter: float) -> None:
    plan = planned(prompt)
    holes = [op.model_dump() for op in plan.operations if op.type == "add_hole"]
    assert holes and all(h["diameter_mm"] == pytest.approx(diameter) for h in holes)


def test_two_holes_for_m5_are_two_holes() -> None:
    plan = planned("Пластина 60×40×8 мм, 2 отверстия под М5")
    assert sum(1 for op in plan.operations if op.type == "add_hole") == 2


def test_a_screw_hole_can_be_added_to_an_existing_part() -> None:
    plan = planned("сделай отверстие под М5", current_operations=box_history())
    assert [op.type for op in plan.operations] == ["create_box", "add_hole"]
    assert plan.operations[-1].model_dump()["diameter_mm"] == pytest.approx(5.7)


# --- objects -------------------------------------------------------------------------------


def test_a_named_object_sizes_the_part() -> None:
    plan = planned("Подставка, чтобы сюда помещался iPhone 17 Pro Max в чехле")
    assert [op.type for op in plan.operations] == ["create_box", "create_box", "boolean"]
    body, cavity, cut = (op.model_dump() for op in plan.operations)
    # phone 78 wide + case 2×2 + sliding fit 0.3 = 82.3; standing in a slot
    assert cavity["width_mm"] == pytest.approx(82.3)
    assert cavity["depth_mm"] == pytest.approx(8.8 + 2.0 + 0.3)
    assert body["width_mm"] == pytest.approx(82.3 + 4)  # 2 mm walls
    assert cut["op"] == "cut" and cut["tool"] == "cavity"
    assert any("iPhone 17 Pro Max" in a for a in plan.assumptions)
    assert any("Чехол" in a for a in plan.assumptions)


def test_a_tray_lays_the_object_flat() -> None:
    plan = planned("A tray for an AA battery")
    body, cavity, _ = (op.model_dump() for op in plan.operations)
    assert cavity["width_mm"] == pytest.approx(14.5 + 0.3)
    assert cavity["depth_mm"] == pytest.approx(14.5 + 0.3)
    assert body["height_mm"] == pytest.approx(50.5 + 0.3 + 3)  # object + floor


def test_an_explicit_outer_size_is_kept_and_the_cavity_centred() -> None:
    plan = planned("Box 120x120x20 mm that fits a credit card")
    body, cavity, _ = (op.model_dump() for op in plan.operations)
    assert (body["width_mm"], body["depth_mm"], body["height_mm"]) == (120, 120, 20)
    assert cavity["width_mm"] == pytest.approx(85.6 + 0.3)
    assert cavity["origin_mm"][0] == pytest.approx((120 - 85.9) / 2)


def test_an_outer_size_too_small_for_the_object_is_questioned() -> None:
    questions = asks("Box 60x60x20 mm that fits a credit card")
    assert "credit card" in questions[0] and "at least" in questions[0]


def test_a_family_without_a_model_is_asked_about() -> None:
    questions = asks("Подставка под iPhone")
    assert "iPhone 17 Pro Max" in questions[0] and "Ш×Г×В" in questions[0]
    questions = asks("a stand for my MacBook")
    assert "MacBook Pro 16" in questions[0]


def test_the_most_specific_name_wins() -> None:
    match = smart_sizes.find_object("держатель под iphone 17 pro max")
    assert isinstance(match, smart_sizes.ObjectMatch)
    assert match.object.id == "iphone-17-pro-max" and match.holder


# --- pipes and tolerances ------------------------------------------------------------------


def test_a_pipe_size_becomes_a_bore_with_a_sliding_fit() -> None:
    plan = planned("Держатель под трубу Ø32")
    types = [op.type for op in plan.operations]
    assert types == ["create_box", "create_cylinder", "boolean"]
    bore = plan.operations[1].model_dump()
    assert bore["diameter_mm"] == pytest.approx(32.3) and bore["axis"] == "y"
    assert plan.operations[0].model_dump()["width_mm"] == pytest.approx(32.3 + 12)


def test_a_tolerance_widens_every_hole_and_nothing_else() -> None:
    history = [
        *box_history(),
        {
            "id": "hole_1",
            "type": "add_hole",
            "schema_version": 1,
            "target": "body",
            "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            "position_mm": [20, 20],
            "diameter_mm": 5.0,
        },
    ]
    plan = planned("Добавь 0,3 мм допуска под PETG", current_operations=history)
    assert [op.type for op in plan.operations] == ["create_box", "add_hole", "set_parameter"]
    fit = plan.operations[-1].model_dump()
    assert fit["operation"] == "hole_1" and fit["parameter"] == "diameter_mm"
    assert fit["value"] == pytest.approx(5.3)
    assert any("0.3" in a for a in plan.assumptions)


def test_refitting_to_a_pipe_changes_the_existing_bore() -> None:
    history = [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 44,
            "depth_mm": 30,
            "height_mm": 44,
        },
        {
            "id": "bore",
            "type": "create_cylinder",
            "schema_version": 1,
            "diameter_mm": 25,
            "height_mm": 32,
            "axis": "y",
            "origin_mm": [22, -1, 22],
        },
        {
            "id": "cut_bore",
            "type": "boolean",
            "schema_version": 1,
            "op": "cut",
            "target": "body",
            "tool": "bore",
        },
    ]
    plan = planned("подгони под трубу Ø32", current_operations=history)
    fit = plan.operations[-1].model_dump()
    assert fit["type"] == "set_parameter" and fit["operation"] == "bore"
    assert fit["value"] == pytest.approx(32.3)


def test_a_tolerance_with_nothing_round_to_adjust_is_a_question() -> None:
    questions = asks("add 0.3 mm clearance", current_operations=box_history())
    assert "no holes" in questions[0]
