"""Manual parametric edits (T-055, F-061): typed operations without the planner.

The LLM is one way to author an OperationPlan; the numeric inspector is another.
Both end up in the same place — a validated plan replayed by the deterministic
kernel into a new immutable version — so a manual edit is the version's operation
log plus the operations the client asked for, validated against the same registry.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import ProjectVersion
from app.services import ai_commands, jobs, projects
from app.services.authz import require_workspace_role

EDIT_JOB = "manual_edit"
MAX_EDIT_OPERATIONS = 32


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


def expected_outputs(version: ProjectVersion) -> list[str]:
    """Keep naming the body the version already shows, so the edit replaces it."""
    provenance = version.provenance or {}
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
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    # Validate now so the user sees the problem in the response, not in a failed job.
    plan = build_plan(db, version=version, operations=operations, label=label)
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=EDIT_JOB,
        input={
            "version_id": str(version.id),
            "operations": operations,
            "label": label,
            "goal": plan.goal,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
