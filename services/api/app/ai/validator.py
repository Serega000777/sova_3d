"""Plan validator against the capability registry (T-044).

Four layers, each producing actionable messages the planner can act on
in a repair round:
1. structure — the loose PlannerOutput parses;
2. registry — every operation type is in OPERATION_TYPES and schema_version 1;
3. semantics — the strict OperationPlan model (units, bounds, references,
   selectors, consumed tools);
4. scope — with a viewport selection, the change stays inside it (T-051).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.ai.contract import PlannerOutput
from app.geometry.operations import OPERATION_TYPES, Operation, OperationPlan, parse_plan
from app.geometry.region import RegionSelection

MAX_OPERATIONS = 256


class ValidationOutcome(BaseModel):
    ok: bool
    plan: OperationPlan | None = None
    errors: list[str] = Field(default_factory=list)
    rejected_types: list[str] = Field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.plan and self.plan.needs_clarification)


def validate_output(
    output: PlannerOutput | dict[str, Any],
    *,
    scope: Sequence[str] = (),
    base_operations: Sequence[dict[str, Any]] = (),
    region: RegionSelection | None = None,
) -> ValidationOutcome:
    payload = output.model_dump() if isinstance(output, PlannerOutput) else dict(output)
    errors: list[str] = []
    rejected: list[str] = []

    operations = payload.get("operations") or []
    if not isinstance(operations, list):
        return ValidationOutcome(ok=False, errors=["operations must be a list"])
    if len(operations) > MAX_OPERATIONS:
        errors.append(f"too many operations ({len(operations)} > {MAX_OPERATIONS})")

    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            errors.append(f"operations[{index}] must be an object")
            continue
        op_type = op.get("type")
        if op_type not in OPERATION_TYPES:
            rejected.append(str(op_type))
            errors.append(
                f"operations[{index}] ({op.get('id', '?')}): unsupported type {op_type!r}; "
                f"allowed: {', '.join(OPERATION_TYPES)}"
            )
        if op.get("schema_version") != 1:
            errors.append(f"operations[{index}] ({op.get('id', '?')}): schema_version must be 1")
    if errors:
        return ValidationOutcome(ok=False, errors=errors, rejected_types=sorted(set(rejected)))

    try:
        plan = parse_plan({"schema_version": 1, **payload})
    except ValidationError as exc:
        return ValidationOutcome(ok=False, errors=_format_errors(exc))
    if plan.needs_clarification and plan.operations:
        return ValidationOutcome(
            ok=False,
            errors=["required_clarifications must be empty when operations are given"],
        )
    scope_errors = _check_scope(plan, scope, base_operations)
    if scope_errors:
        return ValidationOutcome(ok=False, errors=scope_errors)
    region_errors = _check_region(plan, region, base_operations)
    if region_errors:
        return ValidationOutcome(ok=False, errors=region_errors)
    return ValidationOutcome(ok=True, plan=plan)


AXES = ("x", "y", "z")


def _check_region(
    plan: OperationPlan,
    region: RegionSelection | None,
    base_operations: Sequence[dict[str, Any]],
) -> list[str]:
    """T-103: the user circled an area — new geometry belongs inside it.

    Only the operations this plan adds are checked. Replaying the model's history touches
    the whole model by definition, and the user did not ask for that to move.
    """
    if region is None:
        return []
    box = region.bounds()
    limits = dict(zip(AXES, zip(box.min_mm, box.max_mm, strict=True), strict=True))
    base_ids = {str(op.get("id")) for op in base_operations if op.get("id")}
    errors: list[str] = []
    for op in plan.operations:
        if op.id in base_ids:
            continue
        for label, coords in _placements(op):
            outside = [
                f"{axis}={value:.1f} (region {limits[axis][0]:.1f}..{limits[axis][1]:.1f})"
                for axis, value in coords.items()
                if not (limits[axis][0] - 0.001 <= value <= limits[axis][1] + 0.001)
            ]
            if outside:
                errors.append(
                    f"operation {op.id!r} puts {label} outside the region the user "
                    f"outlined: {', '.join(outside)} mm"
                )
    return list(dict.fromkeys(errors))[:20]


def _placements(op: Operation) -> list[tuple[str, dict[str, float]]]:
    """Where an operation puts geometry, per axis, as far as it is knowable.

    A hole is positioned on the face it drills, so only the two in-plane axes are known
    here; the third is the face's own and the region's depth already covers it.
    """
    params = op.model_dump(mode="json")
    found: list[tuple[str, dict[str, float]]] = []

    origin = params.get("origin_mm")
    if isinstance(origin, list) and len(origin) == 3:
        corner = {axis: float(value) for axis, value in zip(AXES, origin, strict=True)}
        found.append(("its origin", corner))
        sizes = [params.get("width_mm"), params.get("depth_mm"), params.get("height_mm")]
        if all(isinstance(value, int | float) for value in sizes):
            extents = [float(value) for value in sizes if isinstance(value, int | float)]
            found.append(
                (
                    "its far corner",
                    {axis: corner[axis] + size for axis, size in zip(AXES, extents, strict=True)},
                )
            )

    position = params.get("position_mm")
    face = params.get("face")
    if isinstance(position, list) and len(position) == 2 and isinstance(face, dict):
        normal = str(face.get("axis", "z"))
        plane = [axis for axis in AXES if axis != normal]
        found.append(("its position", dict(zip(plane, (float(v) for v in position), strict=True))))
    return found


def _check_scope(
    plan: OperationPlan,
    scope: Sequence[str],
    base_operations: Sequence[dict[str, Any]],
) -> list[str]:
    """T-051: with a selection active, nothing outside it may change.

    A plan replays the version's history, so "outside the selection" means either
    rewriting an operation that was already there, or aiming a new operation at a
    body that existed before this command and was not selected.
    """
    if not scope:
        return []
    selected = set(scope)
    base = {str(op.get("id")): op for op in base_operations if op.get("id")}
    errors: list[str] = []
    for op in plan.operations:
        params = op.model_dump(mode="json")
        previous = base.get(op.id)
        if previous is not None:
            if op.id not in selected and params != {**previous, "id": op.id}:
                errors.append(
                    f"operation {op.id!r} is outside the selection "
                    f"({', '.join(sorted(selected))}) but its parameters changed"
                )
            continue
        for ref in _targets(params):
            if ref in base and ref not in selected:
                errors.append(
                    f"operation {op.id!r} targets {ref!r}, which is outside the selection "
                    f"({', '.join(sorted(selected))})"
                )
    return list(dict.fromkeys(errors))[:20]


def _targets(params: dict[str, Any]) -> list[str]:
    """Body references an operation acts on."""
    return [str(params[key]) for key in ("target", "tool", "operation") if params.get(key)]


def _format_errors(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"] if part != "operations") or "plan"
        messages.append(f"{location}: {error['msg']}")
    # Deduplicate while keeping order; discriminated unions repeat the same message per branch.
    return list(dict.fromkeys(messages))[:20]
