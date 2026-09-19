"""`rollback` job (T-123, F-016): "верни как было два часа назад" typed as a command.

No planner and no kernel — the sentence resolves to an earlier version and that version's
content becomes a new one — but it runs as a job so every client's "Build" flow (poll the
job, show what it made) works unchanged, and the AI history shows what was asked.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.api.errors import ValidationFailedError
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import AIRequest, AIRequestStatus
from app.services import history


@register(history.ROLLBACK_JOB)
def handle_rollback(ctx: JobContext) -> dict[str, Any]:
    request_id = ctx.job.input.get("ai_request_id")
    request = ctx.db.get(AIRequest, uuid.UUID(str(request_id))) if request_id else None
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    expression = str(ctx.job.input["expression"])
    if ctx.job.created_by is None:
        raise JobFailureError("no_user", "a rollback needs the user who asked for it")
    try:
        version = history.rollback(
            ctx.db, user_id=ctx.job.created_by, project_id=project_id, expression=expression
        )
    except ValidationFailedError as exc:
        if request is not None:
            request.status = AIRequestStatus.failed
            request.plan_errors = [exc.message]
            ctx.db.flush()
        raise JobFailureError("rollback_failed", exc.message, details=exc.details) from exc
    if request is not None:
        request.status = AIRequestStatus.executed
        request.result_version_id = version.id
        request.output_plan = {"rollback": version.provenance}
        ctx.db.flush()
    ctx.progress(100, "done")
    provenance = version.provenance or {}
    return {
        "version_id": str(version.id),
        "restored_version_id": provenance.get("restored_version_id"),
        "restored_sequence_no": provenance.get("restored_sequence_no"),
        "how": provenance.get("how"),
        "ai_request_id": str(request.id) if request else None,
        "status": "executed",
    }
