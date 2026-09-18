"""AI commands: F-001/F-003/F-062 intent -> async plan/execution job (T-045, T-042, T-048)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.ai.contract import TargetIntent
from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, SettingsDep
from app.models.core import Workspace, WorkspaceRole
from app.models.execution import AIRequest, AIRequestStatus, JobStatus
from app.services import ai_commands, usage
from app.services.authz import require_workspace_role

router = APIRouter(tags=["ai"])


class AICommandCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    project_version_id: uuid.UUID | None = None
    selection_entity_ids: list[str] = Field(default_factory=list, max_length=256)
    units: str = Field(default="mm", pattern="^mm$")
    target: TargetIntent = "print"
    printer_context: dict[str, Any] = Field(default_factory=dict)
    client_capabilities: dict[str, Any] = Field(default_factory=dict)
    # T-052: build it, but leave it a draft the user accepts or rejects.
    preview: bool = False


class AICommandAccepted(BaseModel):
    ai_request_id: uuid.UUID
    job_id: uuid.UUID
    status: AIRequestStatus
    job_status: JobStatus


class ClarifyBody(BaseModel):
    answers: list[str] = Field(min_length=1, max_length=20)


class AIRequestOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_version_id: uuid.UUID | None
    job_id: uuid.UUID | None
    prompt: str
    status: AIRequestStatus
    provider: str
    model: str
    clarifications: list[str]
    conversation: list[dict[str, str]]
    plan_errors: list[str]
    output_plan: dict[str, Any] | None
    result_version_id: uuid.UUID | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


class AIHistoryItem(BaseModel):
    """T-048: what the conversational edit history UI renders per turn."""

    id: uuid.UUID
    prompt: str
    status: AIRequestStatus
    clarifications: list[str]
    result_version_id: uuid.UUID | None
    job_id: uuid.UUID | None
    cost_usd: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageOut(BaseModel):
    workspace_id: uuid.UUID
    period_start: datetime
    spent_usd: Decimal
    budget_usd: Decimal
    remaining_usd: Decimal
    entries: int


@router.post(
    "/projects/{project_id}/ai-commands",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AICommandAccepted,
)
def create_ai_command(
    project_id: uuid.UUID,
    body: AICommandCreate,
    db: DbDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> AICommandAccepted:
    request, job = ai_commands.create_command(
        db,
        settings,
        user_id=principal.user_id,
        project_id=project_id,
        prompt=body.prompt,
        project_version_id=body.project_version_id,
        selection_entity_ids=body.selection_entity_ids,
        target=body.target,
        printer_context=body.printer_context,
        client_capabilities=body.client_capabilities,
        preview=body.preview,
        idempotency_key=idempotency_key,
    )
    return AICommandAccepted(
        ai_request_id=request.id, job_id=job.id, status=request.status, job_status=job.status
    )


@router.post(
    "/ai-requests/{request_id}/clarify",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AICommandAccepted,
)
def clarify_ai_request(
    request_id: uuid.UUID,
    body: ClarifyBody,
    db: DbDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> AICommandAccepted:
    request, job = ai_commands.clarify(
        db, settings, user_id=principal.user_id, request_id=request_id, answers=body.answers
    )
    return AICommandAccepted(
        ai_request_id=request.id, job_id=job.id, status=request.status, job_status=job.status
    )


@router.get("/ai-requests/{request_id}", response_model=AIRequestOut)
def get_ai_request(request_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> AIRequestOut:
    request = ai_commands.get_request(db, user_id=principal.user_id, request_id=request_id)
    return AIRequestOut.model_validate(request)


@router.get("/projects/{project_id}/ai-requests", response_model=list[AIHistoryItem])
def list_ai_requests(
    project_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AIHistoryItem]:
    rows: list[AIRequest] = ai_commands.list_requests(
        db, user_id=principal.user_id, project_id=project_id, limit=limit, offset=offset
    )
    return [AIHistoryItem.model_validate(row) for row in rows]


@router.get("/usage", response_model=UsageOut)
def get_usage(
    workspace_id: uuid.UUID, db: DbDep, settings: SettingsDep, principal: PrincipalDep
) -> UsageOut:
    require_workspace_role(db, principal.user_id, workspace_id, WorkspaceRole.viewer)
    workspace = db.get(Workspace, workspace_id)
    assert workspace is not None
    since = ai_commands.month_start()
    totals = usage.workspace_totals(db, workspace_id, since=since)
    budget = ai_commands.workspace_budget(workspace, settings)
    return UsageOut(
        workspace_id=workspace_id,
        period_start=since,
        spent_usd=totals.cost_usd,
        budget_usd=budget,
        remaining_usd=max(budget - totals.cost_usd, Decimal("0")),
        entries=totals.entries,
    )
