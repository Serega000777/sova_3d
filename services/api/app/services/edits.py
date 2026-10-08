"""Manual parametric edits (T-055, F-061): typed operations without the planner.

The LLM is one way to author an OperationPlan; the numeric inspector is another.
Both end up in the same place — a validated plan replayed by the deterministic
kernel into a new immutable version — so a manual edit is the version's operation
log plus the operations the client asked for, validated against the same registry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job, Operation
from app.models.versioning import ProjectVersion
from app.services import ai_commands, jobs, projects
from app.services.authz import require_workspace_role

EDIT_JOB = "manual_edit"
MAX_EDIT_OPERATIONS = 32


@dataclass(frozen=True)
class StackOperation:
    operation: dict[str, Any]
    enabled: bool


def operation_stack(db: Session, version_id: uuid.UUID) -> list[StackOperation]:
    """Return the complete stored stack, including disabled features, in display order."""
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == version_id)
        .order_by(Operation.sequence_no)
    ).all()
    return [
        StackOperation(
            operation={
                "id": row.params.get("id", f"op_{row.sequence_no}"),
                "type": row.operation_type,
                "schema_version": row.schema_version,
                **{
                    key: value
                    for key, value in row.params.items()
                    if key not in ("id", "type", "schema_version")
                },
            },
            enabled=row.enabled,
        )
        for row in rows
    ]


def _final_bodies(operations: list[dict[str, Any]]) -> list[str]:
    creators = {
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_cone",
        "create_torus",
        "extrude",
        "loft",
        "sweep",
        "revolve",
        "nurbs_surface",
        "analytic_surface_patch",
    }
    bodies: list[str] = []
    for operation in operations:
        if operation.get("type") in creators:
            bodies.append(str(operation["id"]))
        if operation.get("type") == "boolean":
            tool = str(operation.get("tool"))
            bodies = [body for body in bodies if body != tool]
    return bodies


def build_stack_plan(
    db: Session,
    *,
    version: ProjectVersion,
    items: list[dict[str, Any]],
    label: str | None,
) -> tuple[OperationPlan, list[StackOperation]]:
    """Validate a full-stack reorder/toggle and return the executable active plan.

    The request names every stored operation exactly once.  Pydantic's normal OperationPlan
    validation then rejects an enabled feature moved before, or left without, its dependency.
    """
    existing = operation_stack(db, version.id)
    if not existing:
        raise ValidationFailedError(
            "this version has no parametric history to edit",
            {"version_id": str(version.id)},
        )
    if len(items) != len(existing):
        raise ValidationFailedError(
            "the operation stack must include every stored operation exactly once",
            {"expected": len(existing), "received": len(items)},
        )
    by_id = {str(item.operation["id"]): item for item in existing}
    requested_ids = [str(item.get("id", "")) for item in items]
    if len(set(requested_ids)) != len(requested_ids) or set(requested_ids) != set(by_id):
        raise ValidationFailedError(
            "the operation stack contains missing, duplicate, or unknown operation ids",
            {"expected_ids": list(by_id), "received_ids": requested_ids},
        )
    ordered = [
        StackOperation(by_id[operation_id].operation, bool(item.get("enabled", True)))
        for operation_id, item in zip(requested_ids, items, strict=True)
    ]
    active = [item.operation for item in ordered if item.enabled]
    if not active:
        raise ValidationFailedError("at least one operation must remain enabled")
    final_bodies = _final_bodies(active)
    if not final_bodies:
        raise ValidationFailedError("the enabled operation stack does not produce a body")
    prior_outputs = expected_outputs(version)
    outputs = [name for name in prior_outputs if name in final_bodies] or final_bodies[-1:]
    try:
        plan = parse_plan(
            {
                "schema_version": 1,
                "goal": label or "Edit operation stack",
                "operations": active,
                "expected_outputs": outputs,
            }
        )
    except ValueError as exc:
        raise ValidationFailedError(
            "the enabled operation stack does not produce a valid plan", {"error": str(exc)}
        ) from exc
    return plan, ordered


def build_plan(
    db: Session, *, version: ProjectVersion, operations: list[dict[str, Any]], label: str | None
) -> OperationPlan:
    """Replay the version's operations, then append the requested ones."""
    base = ai_commands.current_operations(db, version.id)
    if not base:
        raise ValidationFailedError(
            "this version has no parametric history to edit",
            {
                "version_id": str(version.id),
                "hint": "manual edits need a model built from operations",
            },
        )
    if not operations:
        raise ValidationFailedError("at least one operation is required")
    if len(operations) > MAX_EDIT_OPERATIONS:
        raise ValidationFailedError(
            f"too many operations ({len(operations)} > {MAX_EDIT_OPERATIONS})"
        )

    used = {op.get("id") for op in base}
    appended: list[dict[str, Any]] = []
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ValidationFailedError(f"operations[{index - 1}] must be an object")
        op = {"schema_version": 1, **operation}
        op_id = op.get("id") or f"edit_{index}"
        while op_id in used:  # client ids never silently overwrite replayed ones
            op_id = f"{op_id}_1"
        op["id"] = op_id
        used.add(op_id)
        appended.append(op)

    payload = {
        "schema_version": 1,
        "goal": label or "Manual edit",
        "operations": [*base, *appended],
        "expected_outputs": expected_outputs(version),
    }
    try:
        return parse_plan(payload)
    except ValueError as exc:
        raise ValidationFailedError(
            "the edit does not produce a valid plan", {"error": str(exc)}
        ) from exc


def build_replacement_plan(*, operations: list[dict[str, Any]], label: str | None) -> OperationPlan:
    """Build a fresh exact feature tree as an immutable child of a mesh version.

    This is intentionally creator-only at the root: references may resolve within the supplied
    block, but no operation may depend on a body from the discarded mesh history.
    """
    if not operations:
        raise ValidationFailedError("at least one operation is required")
    if len(operations) > MAX_EDIT_OPERATIONS:
        raise ValidationFailedError(
            f"too many operations ({len(operations)} > {MAX_EDIT_OPERATIONS})"
        )
    used: set[str] = set()
    fresh: list[dict[str, Any]] = []
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ValidationFailedError(f"operations[{index - 1}] must be an object")
        item = {"schema_version": 1, **operation}
        operation_id = str(item.get("id") or f"profile_{index}")
        if operation_id in used:
            raise ValidationFailedError(
                "replacement operations must have unique ids", {"id": operation_id}
            )
        item["id"] = operation_id
        used.add(operation_id)
        fresh.append(item)
    outputs = _final_bodies(fresh)
    if not outputs:
        raise ValidationFailedError("replacement operations do not produce an exact body")
    try:
        return parse_plan(
            {
                "schema_version": 1,
                "goal": label or "Exact CAD from selected mesh profile",
                "operations": fresh,
                "expected_outputs": outputs[-1:],
            }
        )
    except ValueError as exc:
        raise ValidationFailedError(
            "the replacement does not produce a valid plan", {"error": str(exc)}
        ) from exc


def expected_outputs(version: ProjectVersion) -> list[str]:
    """Keep naming the bodies the version already shows, so the edit replaces them: the
    ones its plan expected when it says (a tray and its lid, F-036), else the last body."""
    provenance = version.provenance or {}
    expected = provenance.get("expected_outputs")
    if isinstance(expected, list) and expected:
        return [str(name) for name in expected]
    bodies = provenance.get("bodies") or []
    names = [b["name"] for b in bodies if isinstance(b, dict) and b.get("name")]
    return names[-1:]


def enqueue_edit(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    operations: list[dict[str, Any]],
    label: str | None = None,
    preview: bool = False,
    replace_history: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if replace_history and operation_stack(db, version.id):
        raise ValidationFailedError(
            "replacement history is only available for imported or scanned mesh versions",
            {
                "version_id": str(version.id),
                "hint": "append the exact operation to the existing parametric feature tree",
            },
        )
    # Validate now so the user sees the problem in the response, not in a failed job.
    plan = (
        build_replacement_plan(operations=operations, label=label)
        if replace_history
        else build_plan(db, version=version, operations=operations, label=label)
    )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=EDIT_JOB,
        input={
            "version_id": str(version.id),
            "operations": operations,
            "label": label,
            "goal": plan.goal,
            "preview": preview,  # T-052: a preview stays a draft until accepted
            "replace_history": replace_history,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


def enqueue_stack_edit(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    items: list[dict[str, Any]],
    label: str | None = None,
    preview: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    plan, _ = build_stack_plan(db, version=version, items=items, label=label)
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=EDIT_JOB,
        input={
            "version_id": str(version.id),
            "operation_stack": items,
            "label": label,
            "goal": plan.goal,
            "preview": preview,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
