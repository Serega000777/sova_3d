"""T-138 (F-009): the construction adapts to the material — as edits on its own plan."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.contract import PlanRequest
from app.ai.planner import StubPlanner, plan_with_repair
from app.engineering.material import adapt
from app.geometry.operations import parse_plan


def organizer() -> list[dict[str, Any]]:
    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(prompt="Organizer 120x80x40 mm with 4 compartments, 2 holes for M4"),
    )
    assert outcome.plan is not None
    return [op.model_dump(mode="json") for op in outcome.plan.operations]


def valid(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> None:
    ops = [*base, *[{"id": f"m{i}", "schema_version": 1, **op} for i, op in enumerate(extra)]]
    parse_plan({"schema_version": 1, "goal": "x", "operations": ops, "expected_outputs": ["body"]})


def edits_of(extra: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {
        (op["operation"], op["parameter"]): op["value"]
        for op in extra
        if op["type"] == "set_parameter"
    }


def test_tpu_thickens_every_wall_floor_and_divider() -> None:
    base = organizer()
    result = adapt(base, material_id="tpu", from_material_id="pla")
    valid(base, result.operations)
    assert result.wall_mm == 2.25  # 5 lines of a 0.4 nozzle
    edits = edits_of(result.operations)
    # outer walls: the first pocket moves in from 2 mm to 2.25 mm on x and y
    assert edits[("pocket_1", "origin_x_mm")] == 2.25
    assert edits[("pocket_1", "origin_y_mm")] == 2.25
    # the divider between pocket 1 and 2 grows from 2 to 2.25: each gives up half
    assert edits[("pocket_1", "width_mm")] == pytest.approx(57 - 0.25 - 0.125)
    assert edits[("pocket_2", "origin_x_mm")] == pytest.approx(61 + 0.125)
    # the floor grows to wall + 1 and the pocket keeps its top
    assert edits[("pocket_1", "origin_z_mm")] == 3.25
    assert edits[("pocket_1", "height_mm")] == pytest.approx(37 - 0.25)
    # holes follow the material's undersize (0.2 -> 0.4)
    assert edits[("hole_1", "diameter_mm")] == pytest.approx(4.7 + 0.2)
    assert any("compartment(s) moved" in change for change in result.changes)


def test_petg_only_touches_the_holes_when_the_walls_already_pass() -> None:
    base = organizer()
    result = adapt(base, material_id="petg", from_material_id="pla")
    valid(base, result.operations)
    assert set(edits_of(result.operations)) == {
        ("hole_1", "diameter_mm"),
        ("hole_2", "diameter_mm"),
    }
    assert edits_of(result.operations)[("hole_1", "diameter_mm")] == pytest.approx(4.8)


def test_a_brittle_material_gets_rounded_corners_once() -> None:
    base = organizer()
    result = adapt(base, material_id="pla", from_material_id="pla")
    assert [op["type"] for op in result.operations] == ["fillet"]
    assert result.operations[0]["radius_mm"] == 1.5
    # already rounded: nothing to do
    rounded = [
        *base,
        {
            "id": "soft",
            "type": "fillet",
            "schema_version": 1,
            "target": "body",
            "edges": {"kind": "edges_parallel_to", "axis": "z"},
            "radius_mm": 1,
        },
    ]
    again = adapt(rounded, material_id="pla", from_material_id="pla")
    assert again.operations == [] and "already suits" in again.changes[0]


def test_a_measured_printer_replaces_the_typical_undersize() -> None:
    base = organizer()
    # the printer was calibrated: holes shrink 0.35 mm whatever the material
    result = adapt(
        base, material_id="petg", from_material_id="pla", undersize_from=0.35, undersize_to=0.35
    )
    assert ("hole_1", "diameter_mm") not in edits_of(result.operations)


def test_compartments_too_small_for_the_walls_are_left_alone() -> None:
    # a slot 4.2 mm wide between 2 mm walls: TPU walls would leave 3.7 mm, too little
    base: list[dict[str, Any]] = [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 8.2,
            "depth_mm": 20,
            "height_mm": 10,
        },
        {
            "id": "slot",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": 4.2,
            "depth_mm": 16,
            "height_mm": 8,
            "origin_mm": [2, 2, 3],
        },
        {
            "id": "cut",
            "type": "boolean",
            "schema_version": 1,
            "op": "cut",
            "target": "body",
            "tool": "slot",
        },
    ]
    result = adapt(base, material_id="tpu", from_material_id="pla")
    assert result.skipped and "left as they are" in result.skipped[0]
    assert not any(op.get("operation") == "slot" for op in result.operations)
