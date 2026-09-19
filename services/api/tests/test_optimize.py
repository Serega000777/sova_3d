"""T-145 (F-007): "make it lighter" is a shell to a wall the material can carry."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.contract import PlanRequest
from app.ai.planner import StubPlanner, plan_with_repair
from app.engineering.optimize import lighten, mass_g
from app.geometry.operations import parse_plan


def built(prompt: str) -> list[dict[str, Any]]:
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt))
    assert outcome.plan is not None, outcome
    return [op.model_dump(mode="json") for op in outcome.plan.operations]


def valid(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> None:
    ops = [*base]
    for i, op in enumerate(extra):
        ops.append({"id": op.get("id") or f"m{i}", "schema_version": 1, **op})
    parse_plan({"schema_version": 1, "goal": "x", "operations": ops, "expected_outputs": ["body"]})


def test_a_block_is_hollowed_to_the_material_wall_open_at_the_bottom() -> None:
    base = built("Box 80x60x40 mm")
    result = lighten(base, material_id="pla")
    valid(base, result.operations)
    assert result.wall_mm == 1.8  # PLA structural 1.6 mm, rounded up to whole 0.45 mm lines
    (shell,) = result.operations
    assert shell["type"] == "shell" and shell["thickness_mm"] == 1.8
    assert shell["open_face"] == {"kind": "face_by_normal", "axis": "z", "sign": "-"}
    assert any("open at the bottom" in c for c in result.changes)
    assert result.density_g_cm3 == 1.24


def test_screw_holes_keep_a_boss_and_are_drilled_again() -> None:
    base = built("Box 80x60x40 mm with 2 holes for M4")
    result = lighten(base, material_id="petg", language="ru")
    valid(base, result.operations)
    kinds = [op["type"] for op in result.operations]
    assert kinds == ["shell", "create_cylinder", "boolean", "add_hole"] * 1 + [
        "create_cylinder",
        "boolean",
        "add_hole",
    ]
    boss = result.operations[1]
    hole = next(op for op in base if op.get("id") == "hole_1")
    assert boss["diameter_mm"] == pytest.approx(hole["diameter_mm"] + 4)
    assert boss["height_mm"] == 40 and boss["origin_mm"][:2] == list(hole["position_mm"])
    assert result.operations[2] == {
        "type": "boolean",
        "op": "fuse",
        "target": "body",
        "tool": "boss_1",
    }
    assert result.operations[3]["diameter_mm"] == hole["diameter_mm"]
    assert any("бобышки" in c for c in result.changes)


def test_a_thin_part_is_left_solid_and_said() -> None:
    base = built("Box 80x60x8 mm")
    result = lighten(base, material_id="pla")
    assert result.operations == [] and "left solid" in result.skipped[0]


def test_hollowing_twice_does_nothing() -> None:
    base = built("Box 80x60x40 mm")
    once = lighten(base, material_id="pla")
    again = lighten(
        [*base, {"id": "h", "schema_version": 1, **once.operations[0]}], material_id="pla"
    )
    assert again.operations == [] and "already hollow" in again.changes[0]


def test_wall_and_opening_can_be_chosen() -> None:
    base = built("Box 80x60x40 mm")
    result = lighten(base, material_id="abs", wall_mm=3.0, opening="none", load="load_bearing")
    (shell,) = result.operations
    assert shell["thickness_mm"] == 3.0 and "open_face" not in shell
    assert any("enclosed" in c for c in result.changes)


def test_mass_follows_the_material_density() -> None:
    assert mass_g(192_000, 1.24) == 238.1  # a solid 80x60x40 PLA block
    assert mass_g(0, 1.24) == 0.0
