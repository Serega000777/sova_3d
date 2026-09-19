"""AI commands (T-045): intent -> AIRequest + Job; clarification loop (T-042);
per-request metering (T-046); workspace quotas (T-047); history (T-048).

The API side only records intent and enqueues. Planning and geometry run in
the job handler (app/jobs/handlers.py) so the request never waits on a model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.contract import PlanRequest
from app.api.errors import APIError, ConflictError, NotFoundError
from app.config import Settings
from app.geometry.region import parse_region
from app.models.core import Workspace, WorkspaceRole
from app.models.execution import AIRequest, AIRequestStatus, Job, JobStatus, Operation
from app.models.usage import UsageKind
from app.services import calibration, history, jobs, printing, projects, usage
from app.services.authz import require_workspace_role

JOB_TYPE = "ai_command"


class QuotaExceededError(APIError):
    status_code = 402
    code = "ai_quota_exceeded"


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def workspace_budget(workspace: Workspace, settings: Settings) -> Decimal:
    if workspace.ai_monthly_budget_usd is not None:
        return Decimal(workspace.ai_monthly_budget_usd)
    return Decimal(str(settings.ai_workspace_monthly_budget_usd))


def month_to_date_cost(db: Session, workspace_id: uuid.UUID) -> Decimal:
    totals = usage.workspace_totals(db, workspace_id, since=month_start())
    return totals.cost_usd


def enforce_quota(db: Session, workspace: Workspace, settings: Settings) -> dict[str, Any]:
    """T-047: refuse new AI work once the month's spend reaches the workspace budget."""
    spent = month_to_date_cost(db, workspace.id)
    budget = workspace_budget(workspace, settings)
    if spent >= budget:
        raise QuotaExceededError(
            "this workspace has used its monthly AI budget",
            {"spent_usd": str(spent), "budget_usd": str(budget)},
        )
    return {"spent_usd": str(spent), "budget_usd": str(budget)}


def current_operations(db: Session, version_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """The version's operation log in plan form, so the planner can replay + edit it."""
    if version_id is None:
        return []
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == version_id)
        .order_by(Operation.sequence_no)
    ).all()
    return [
        {
            "id": row.params.get("id", f"op_{row.sequence_no}"),
            "type": row.operation_type,
            "schema_version": row.schema_version,
            **{k: v for k, v in row.params.items() if k not in ("id", "type", "schema_version")},
        }
        for row in rows
    ]


def create_command(
    db: Session,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    project_version_id: uuid.UUID | None = None,
    selection_entity_ids: list[str] | None = None,
    region: dict[str, Any] | None = None,
    target: str = "print",
    printer_context: dict[str, Any] | None = None,
    client_capabilities: dict[str, Any] | None = None,
    preview: bool = False,
    idempotency_key: str | None = None,
) -> tuple[AIRequest, Job]:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    workspace = db.get(Workspace, project.workspace_id)
    assert workspace is not None
    enforce_quota(db, workspace, settings)

    version_id = project_version_id or project.head_version_id
    if version_id is not None:
        projects.get_version(db, user_id=user_id, version_id=version_id)

    # F-029: a calibrated printer's measured hole undersize reaches every plan for it.
    printer_context = dict(printer_context or {})
    if "hole_undersize_mm" not in printer_context:
        try:
            profile, _ = printing.resolve_inputs(
                db,
                user_id=user_id,
                workspace_id=project.workspace_id,
                printer_profile_id=(
                    uuid.UUID(str(printer_context["printer_profile_id"]))
                    if printer_context.get("printer_profile_id")
                    else None
                ),
                material_id=None,
            )
        except (NotFoundError, ValueError):
            profile = None
        undersize = calibration.undersize_for(profile)
        if undersize is not None:
            printer_context["hole_undersize_mm"] = undersize
            printer_context.setdefault("printer_profile_id", str(profile.id) if profile else None)

    if idempotency_key:
        existing_job = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace.id, Job.idempotency_key == idempotency_key
            )
        )
        if existing_job is not None:
            request = db.get(AIRequest, uuid.UUID(str(existing_job.input["ai_request_id"])))
            if request is not None:
                return request, existing_job

    request = AIRequest(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version_id,
        user_id=user_id,
        prompt=prompt,
        context={
            "units": "mm",
            "target": target,
            "selection_entity_ids": selection_entity_ids or [],
            # T-102: the area the user outlined, already in millimetres.
            "region": parse_region(region).model_dump(mode="json") if region else None,
            "printer_context": printer_context or {},
            "client_capabilities": client_capabilities or {},
            # T-052: a preview stays a draft until the user accepts it.
            "preview": preview,
        },
        provider=settings.ai_provider,
        model=settings.ai_model if settings.ai_provider == "anthropic" else "rules-v1",
    )
    db.add(request)
    db.flush()
    # F-016: "верни как было два часа назад" is history, not geometry — no planner, no kernel.
    is_rollback = history.parse_rollback(prompt) is not None and project.head_version_id
    job = jobs.enqueue(
        db,
        workspace_id=workspace.id,
        job_type=history.ROLLBACK_JOB if is_rollback else JOB_TYPE,
        input=(
            {"ai_request_id": str(request.id), "project_id": str(project.id), "expression": prompt}
            if is_rollback
            else {"ai_request_id": str(request.id)}
        ),
        created_by=user_id,
        project_id=project.id,
        project_version_id=version_id,
        idempotency_key=idempotency_key,
    )
    request.job_id = job.id
    db.flush()
    return request, job


def get_request(db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID) -> AIRequest:
    request = db.get(AIRequest, request_id)
    if request is None:
        raise NotFoundError("ai_request", request_id)
    require_workspace_role(db, user_id, request.workspace_id, WorkspaceRole.viewer)
    return request


def list_requests(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[AIRequest]:
    projects.get_project(db, user_id=user_id, project_id=project_id)
    return list(
        db.scalars(
            sa.select(AIRequest)
            .where(AIRequest.project_id == project_id)
            .order_by(AIRequest.created_at.desc(), AIRequest.id)
            .limit(limit)
            .offset(offset)
        )
    )


def clarify(
    db: Session,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    answers: list[str],
) -> tuple[AIRequest, Job]:
    """T-042: answer the open questions and resume planning on the same request."""
    request = get_request(db, user_id=user_id, request_id=request_id)
    require_workspace_role(db, user_id, request.workspace_id, WorkspaceRole.editor)
    if request.status is not AIRequestStatus.needs_clarification:
        raise ConflictError(
            "request is not waiting for clarification", {"status": request.status.value}
        )
    if not answers or len(answers) != len(request.clarifications):
        raise ConflictError(
            "one answer per open question is required",
            {"questions": request.clarifications},
        )
    workspace = db.get(Workspace, request.workspace_id)
    assert workspace is not None
    enforce_quota(db, workspace, settings)

    request.conversation = [
        *request.conversation,
        *(
            {"question": question, "answer": answer}
            for question, answer in zip(request.clarifications, answers, strict=True)
        ),
    ]
    request.clarifications = []
    request.status = AIRequestStatus.planning
    job = db.get(Job, request.job_id) if request.job_id else None
    if job is not None and job.status is JobStatus.waiting_input:
        job.status = JobStatus.queued
        job.stage = "clarified"
        job.error = None
        db.flush()
    else:
        job = jobs.enqueue(
            db,
            workspace_id=request.workspace_id,
            job_type=JOB_TYPE,
            input={"ai_request_id": str(request.id)},
            created_by=user_id,
            project_id=request.project_id,
            project_version_id=request.project_version_id,
        )
        request.job_id = job.id
    db.flush()
    return request, job


def plan_request_for(db: Session, request: AIRequest) -> PlanRequest:
    context = request.context or {}
    return PlanRequest(
        prompt=request.prompt,
        target=context.get("target", "print"),
        selection_entity_ids=list(context.get("selection_entity_ids", [])),
        region=context.get("region"),
        current_operations=current_operations(db, request.project_version_id),
        printer_context=dict(context.get("printer_context", {})),
        client_capabilities=dict(context.get("client_capabilities", {})),
        conversation=list(request.conversation),
    )


def record_usage(db: Session, request: AIRequest, usages: list[Any], job_id: uuid.UUID) -> Decimal:
    """T-046: one ledger row per provider call, exact tokens and cost."""
    total = Decimal("0")
    for entry in usages:
        usage.record(
            db,
            workspace_id=request.workspace_id,
            kind=UsageKind.ai_tokens,
            quantity=entry.input_tokens + entry.output_tokens,
            unit="token",
            cost_usd=entry.cost_usd,
            credits_delta=-entry.cost_usd,
            user_id=request.user_id,
            job_id=job_id,
            ai_request_id=request.id,
            metadata={
                "provider": entry.provider,
                "model": entry.model,
                "input_tokens": entry.input_tokens,
                "output_tokens": entry.output_tokens,
                "cache_read_tokens": entry.cache_read_tokens,
                "latency_ms": entry.latency_ms,
            },
        )
        total += entry.cost_usd
    request.tokens_in = sum(e.input_tokens for e in usages)
    request.tokens_out = sum(e.output_tokens for e in usages)
    request.cost_usd = (request.cost_usd or Decimal("0")) + total
    db.flush()
    return total
