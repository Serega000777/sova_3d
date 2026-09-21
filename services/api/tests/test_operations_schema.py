"""T-032: Operation schema v1 — strict parsing, reference resolution, published schema."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.geometry.operations import (
    OPERATION_TYPES,
    CreateBox,
    OperationPlan,
    parse_plan,
)

CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts"
EXAMPLES = sorted((CONTRACTS / "examples").glob("*.plan.json"))
needs_contracts = pytest.mark.skipif(
    not CONTRACTS.is_dir(), reason="packages/contracts not available outside the monorepo"
)


def box(op_id: str = "b", **overrides: object) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "create_box",
        "schema_version": 1,
        "width_mm": 200,
        "depth_mm": 100,
        "height_mm": 50,
        **overrides,
    }


def plan(*operations: dict[str, object], **overrides: object) -> dict[str, object]:
    return {"schema_version": 1, "goal": "test", "operations": list(operations), **overrides}


@needs_contracts
@pytest.mark.parametrize("path", EXAMPLES, ids=[p.name for p in EXAMPLES])
def test_examples_parse(path: Path) -> None:
    parsed = parse_plan(json.loads(path.read_text("utf-8")))
    assert parsed.operations and not parsed.needs_clarification
    assert {op.type for op in parsed.operations} <= set(OPERATION_TYPES)


@needs_contracts
def test_published_schema_matches_models() -> None:
    published = json.loads((CONTRACTS / "operation-plan.schema.json").read_text("utf-8"))
    expected = OperationPlan.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert published == expected, "run: uv run python -m app.geometry.operations --emit-schema"


def test_unknown_operation_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="type"):
        parse_plan(plan({"id": "x", "type": "generate_mesh_from_text", "schema_version": 1}))


def test_extra_and_unitless_parameters_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        parse_plan(plan(box(width="200")))
    with pytest.raises(ValidationError, match="width_mm"):
        parse_plan(plan(box(width_mm=0)))
    with pytest.raises(ValidationError, match="width_mm"):
        parse_plan(plan(box(width_mm=50_000)))


def test_schema_version_is_pinned() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        parse_plan(plan(box(schema_version=2)))
    with pytest.raises(ValidationError, match="schema_version"):
        parse_plan({**plan(box()), "schema_version": 2})


def test_references_must_resolve_in_order() -> None:
    cut = {
        "id": "c",
        "type": "boolean",
        "schema_version": 1,
        "op": "cut",
        "target": "b",
        "tool": "t",
    }
    with pytest.raises(ValidationError, match="unknown body 't'"):
        parse_plan(plan(box("b"), cut))
    with pytest.raises(ValidationError, match="unknown body"):
        parse_plan(plan(cut, box("b"), box("t")))  # order matters
    parsed = parse_plan(plan(box("b"), box("t"), cut))
    assert [op.id for op in parsed.operations] == ["b", "t", "c"]

    # A consumed tool cannot be referenced afterwards.
    translate = {
        "id": "mv",
        "type": "translate",
        "schema_version": 1,
        "target": "t",
        "offset_mm": [1, 0, 0],
    }
    with pytest.raises(ValidationError, match="unknown body 't'"):
        parse_plan(plan(box("b"), box("t"), cut, translate))


def test_duplicate_ids_and_self_boolean_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate operation id"):
        parse_plan(plan(box("b"), box("b")))
    with pytest.raises(ValidationError, match="different bodies"):
        parse_plan(
            plan(
                box("b"),
                {
                    "id": "c",
                    "type": "boolean",
                    "schema_version": 1,
                    "op": "fuse",
                    "target": "b",
                    "tool": "b",
                },
            )
        )


def test_set_parameter_targets_an_earlier_operation() -> None:
    edit = {
        "id": "e",
        "type": "set_parameter",
        "schema_version": 1,
        "operation": "b",
        "parameter": "height_mm",
        "value": 60,
    }
    parsed = parse_plan(plan(box("b"), edit))
    assert parsed.operations[1].type == "set_parameter"
    with pytest.raises(ValidationError, match="edits unknown operation"):
        parse_plan(plan(edit, box("b")))
    with pytest.raises(ValidationError, match="parameter"):
        parse_plan(plan(box("b"), {**edit, "parameter": "colour"}))


def test_linear_pattern_has_bounded_count_and_exact_spacing() -> None:
    pattern = {
        "id": "copies",
        "type": "linear_pattern",
        "schema_version": 1,
        "target": "b",
        "axis": "x",
        "count": 4,
        "spacing_mm": 12.5,
    }
    parsed = parse_plan(plan(box("b"), pattern))
    assert parsed.operations[1].type == "linear_pattern"
    with pytest.raises(ValidationError, match="count"):
        parse_plan(plan(box("b"), {**pattern, "count": 1}))
    with pytest.raises(ValidationError, match="spacing_mm"):
        parse_plan(plan(box("b"), {**pattern, "spacing_mm": 0}))


def test_clarifications_block_execution() -> None:
    parsed = parse_plan(plan(required_clarifications=["Which side should the holes be on?"]))
    assert parsed.needs_clarification and parsed.operations == []


def test_defaults_are_explicit_and_frozen() -> None:
    parsed = parse_plan(plan(box("b")))
    op = parsed.operations[0]
    assert isinstance(op, CreateBox)
    assert op.origin_mm == (0.0, 0.0, 0.0) and op.centered is False
    with pytest.raises(ValidationError):
        op.width_mm = 1  # type: ignore[misc]
