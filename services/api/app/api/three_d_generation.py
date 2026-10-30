"""Provider-neutral 3D generation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.ai.three_d import (
    GenerationEstimate,
    GenerationLifecycleStatus,
    GenerationRequest,
    ProviderCapabilities,
    QualityReport,
)
from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, SettingsDep
from app.api.schemas import JobAccepted
from app.services import generation

router = APIRouter(tags=["3D generation"])


class ThreeDGenerationOut(BaseModel):
    job_id: uuid.UUID
    project_id: uuid.UUID
    status: GenerationLifecycleStatus
    progress: int
    stage: str | None
    provider: str
    provider_model: str
    provider_version: str | None
    provider_job_id: str | None
    request: GenerationRequest
    estimate: GenerationEstimate
    raw_asset_id: uuid.UUID | None
    normalized_asset_id: uuid.UUID | None
    quality_report: QualityReport | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    cost_usd: Decimal
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.get("/3d-generation/providers", response_model=list[ProviderCapabilities])
def list_three_d_providers(
    settings: SettingsDep, principal: PrincipalDep
) -> list[ProviderCapabilities]:
    del principal
    return generation.provider_capabilities(settings)


@router.post("/projects/{project_id}/3d-generations/estimate", response_model=GenerationEstimate)
def estimate_three_d_generation(
    project_id: uuid.UUID,
    body: GenerationRequest,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> GenerationEstimate:
    return generation.estimate_generation(
        db,
        settings=settings,
        user_id=principal.user_id,
        project_id=project_id,
        request=body,
    )


@router.post(
    "/projects/{project_id}/3d-generations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_three_d_generation(
    project_id: uuid.UUID,
    body: GenerationRequest,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job, _ = generation.start_provider_generation(
        db,
        settings=settings,
        user_id=principal.user_id,
        project_id=project_id,
        request=body,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/3d-generations/{job_id}", response_model=ThreeDGenerationOut)
def get_three_d_generation(
    job_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> ThreeDGenerationOut:
    job, record = generation.get_provider_generation(db, user_id=principal.user_id, job_id=job_id)
    return ThreeDGenerationOut(
        job_id=job.id,
        project_id=record.project_id,
        status=generation.normalized_status(job),
        progress=job.progress,
        stage=job.stage,
        provider=record.provider,
        provider_model=record.provider_model,
        provider_version=record.provider_version,
        provider_job_id=record.provider_job_id,
        request=GenerationRequest.model_validate(record.request),
        estimate=GenerationEstimate.model_validate(record.estimate),
        raw_asset_id=record.raw_asset_id,
        normalized_asset_id=record.normalized_asset_id,
        quality_report=(
            QualityReport.model_validate(record.quality_report)
            if record.quality_report is not None
            else None
        ),
        result=job.result,
        error=job.error,
        cost_usd=job.cost_usd,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
