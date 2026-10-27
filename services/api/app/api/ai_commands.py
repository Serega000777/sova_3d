"""AI commands: F-001/F-003/F-062 intent -> async plan/execution job (T-045, T-042, T-048)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, model_validator

from app.ai.contract import MAX_PHOTOS, TargetIntent
from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, SettingsDep
from app.geometry.region import RegionSelection
from app.models.core import Workspace, WorkspaceRole
from app.models.execution import AIRequest, AIRequestStatus, JobStatus
from app.services import ai_commands, usage
from app.services.authz import require_workspace_role

router = APIRouter(tags=["ai"])

ReplacementDimension = Literal["length", "width", "height", "hole_diameter"]
REPLACEMENT_DIMENSIONS: tuple[ReplacementDimension, ...] = (
    "length",
    "width",
    "height",
    "hole_diameter",
)


class ReplacementPartViews(BaseModel):
    """Four user-labelled sides; labels are evidence, not inferred camera poses."""

    front: uuid.UUID
    right: uuid.UUID
    back: uuid.UUID
    left: uuid.UUID

    @model_validator(mode="after")
    def views_are_distinct(self) -> ReplacementPartViews:
        if len({self.front, self.right, self.back, self.left}) != 4:
            raise ValueError("replacement-part views must use four distinct image assets")
        return self

    def asset_ids(self) -> list[uuid.UUID]:
        return [self.front, self.right, self.back, self.left]


class ReplacementPartCapture(BaseModel):
    """Bounded evidence for camera → replacement-part planning."""

    views: ReplacementPartViews
    measurements: dict[
        ReplacementDimension,
        Annotated[Decimal, Field(gt=0, le=10_000)],
    ] = Field(
        default_factory=dict,
        max_length=4,
        description=(
            "One or more user-measured millimetre dimensions; unspecified values are unknown."
        ),
    )
    # Compatibility for clients released before the multi-measurement contract. New clients
    # send `measurements`; the server canonicalizes either representation before persistence.
    known_dimension: ReplacementDimension | None = None
    known_mm: Decimal | None = Field(default=None, gt=0, le=10_000)

    @model_validator(mode="after")
    def measurement_evidence_is_unambiguous(self) -> ReplacementPartCapture:
        has_legacy_dimension = self.known_dimension is not None
        has_legacy_value = self.known_mm is not None
        if has_legacy_dimension != has_legacy_value:
            raise ValueError("known_dimension and known_mm must be supplied together")
        if self.measurements and has_legacy_dimension:
            raise ValueError(
                "use measurements or the legacy known_dimension/known_mm pair, not both"
            )
        if not self.measurements and not has_legacy_dimension:
            raise ValueError("at least one measured replacement-part dimension is required")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        if self.measurements:
            measurements = self.measurements
        else:
            assert self.known_dimension is not None and self.known_mm is not None
            measurements = {self.known_dimension: self.known_mm}
        return {
            "views": self.views.model_dump(mode="json"),
            "measurements": {
                dimension: str(measurements[dimension])
                for dimension in REPLACEMENT_DIMENSIONS
                if dimension in measurements
            },
        }


class AICommandCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    project_version_id: uuid.UUID | None = None
    selection_entity_ids: list[str] = Field(default_factory=list, max_length=256)
    # The area the user outlined on the model, in millimetres (T-102, F-062).
    region: RegionSelection | None = None
    units: str = Field(default="mm", pattern="^mm$")
    target: TargetIntent = "print"
    printer_context: dict[str, Any] = Field(default_factory=dict)
    client_capabilities: dict[str, Any] = Field(default_factory=dict)
    # T-052: build it, but leave it a draft the user accepts or rejects.
    preview: bool = False
    # F-019: uploaded photos of the object (JPEG/PNG assets of this workspace), and what in
    # them has a known size — "credit card", "the width is 80 mm".
    image_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_PHOTOS)
    reference: str | None = Field(default=None, max_length=200)
    # F-076: a hand-drawn sketch of the object, uploaded like a photo (shares the MAX_PHOTOS
    # budget with image_asset_ids) but flagged so the planner treats it as a design reference.
    sketch_asset_id: uuid.UUID | None = None
    # Reference 71: a dedicated replacement-part workflow must carry four explicitly
    # labelled views and one real measurement. It cannot silently reuse an optional hint.
    replacement_part: ReplacementPartCapture | None = None

    @model_validator(mode="after")
    def replacement_evidence_is_unambiguous(self) -> AICommandCreate:
        if self.replacement_part is None:
            return self
        if self.image_asset_ids or self.sketch_asset_id is not None or self.reference is not None:
            raise ValueError(
                "replacement_part supplies its own views and measurement; "
                "image_asset_ids, sketch_asset_id and reference must be omitted"
            )
        return self


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
    photo_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    sketch_asset_id: uuid.UUID | None = None

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
    # F-019: the turn started from photos (the ids let a client show them).
    photo_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    sketch_asset_id: uuid.UUID | None = None

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
    replacement = body.replacement_part
    replacement_payload = replacement.canonical_payload() if replacement else None
    request, job = ai_commands.create_command(
        db,
        settings,
        user_id=principal.user_id,
        project_id=project_id,
        prompt=body.prompt,
        project_version_id=body.project_version_id,
        selection_entity_ids=body.selection_entity_ids,
        region=body.region.model_dump(mode="json") if body.region else None,
        target=body.target,
        printer_context=body.printer_context,
        client_capabilities=body.client_capabilities,
        preview=body.preview,
        idempotency_key=idempotency_key,
        image_asset_ids=(replacement.views.asset_ids() if replacement else body.image_asset_ids),
        reference=body.reference,
        sketch_asset_id=body.sketch_asset_id,
        replacement_part=replacement_payload,
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


class VariantsBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=3, ge=2, le=4)
    project_version_id: uuid.UUID | None = None
    selection_entity_ids: list[str] = Field(default_factory=list)
    region: RegionSelection | None = None
    target: TargetIntent = "print"


class VariantAccepted(BaseModel):
    strategy: str
    title_en: str
    title_ru: str
    ai_request_id: uuid.UUID
    job_id: uuid.UUID


@router.post(
    "/projects/{project_id}/variants",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=list[VariantAccepted],
)
def create_variants(
    project_id: uuid.UUID,
    body: VariantsBody,
    db: DbDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> list[VariantAccepted]:
    """F-075: several constructive answers to one request, each a preview to pick from."""
    from app.ai.contract import VARIANT_STRATEGIES

    made = ai_commands.create_variants(
        db,
        settings,
        user_id=principal.user_id,
        project_id=project_id,
        prompt=body.prompt,
        count=body.count,
        project_version_id=body.project_version_id,
        selection_entity_ids=body.selection_entity_ids,
        region=body.region.model_dump(mode="json") if body.region else None,
        target=body.target,
    )
    return [
        VariantAccepted(
            strategy=strategy,
            title_en=VARIANT_STRATEGIES[strategy][0],
            title_ru=VARIANT_STRATEGIES[strategy][1],
            ai_request_id=request.id,
            job_id=job.id,
        )
        for strategy, request, job in made
    ]


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
