"""Organic shapes from a description (F-001/F-075).

The kernel builds what has dimensions; a figurine, an animal or a vase has none, so it is
generated as a mesh by a learned model instead. The result is a new version like any
import — honest about being a guess at a shape, then repaired and checked like any mesh.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.providers.shap_e_3d import ShapEThreeDProvider
from app.ai.three_d import (
    GenerationEstimate,
    GenerationLifecycleStatus,
    GenerationPurpose,
    GenerationRequest,
    ProviderCapabilities,
)
from app.ai.three_d_router import ProviderRoute, RoutingDecision, select_provider
from app.api.errors import APIError, ConflictError, NotFoundError, ValidationFailedError
from app.config import Settings
from app.models.core import WorkspaceRole
from app.models.execution import FailureClass, Job, JobStatus
from app.models.generation import ThreeDGeneration
from app.models.versioning import Asset
from app.services import jobs, projects
from app.services.authz import require_workspace_role

GENERATE_MESH_JOB = "generate_mesh"


class MeshGenerationNotEnabledError(APIError):
    status_code = 501
    code = "mesh_generation_not_enabled"


def provider_routes(settings: Settings) -> list[ProviderRoute]:
    if settings.mesh_generation_provider == "none":
        return []
    if settings.mesh_generation_provider == "shap_e":
        return [
            ProviderRoute(
                provider=ShapEThreeDProvider(),
                default_priority=50,
                purpose_priority={GenerationPurpose.draft: 10},
            )
        ]
    raise MeshGenerationNotEnabledError(
        "the configured 3D generation provider is unavailable",
        {"provider": settings.mesh_generation_provider},
    )


def route_provider(settings: Settings, request: GenerationRequest) -> RoutingDecision:
    routes = provider_routes(settings)
    if not routes:
        raise MeshGenerationNotEnabledError(
            "3D generation is not enabled on this server",
            {"setting": "MESH_GENERATION_PROVIDER"},
        )
    return select_provider(routes, request)


def provider_capabilities(settings: Settings) -> list[ProviderCapabilities]:
    return [route.provider.capabilities() for route in provider_routes(settings)]


def _validate_request_assets(
    db: Session, *, workspace_id: uuid.UUID, request: GenerationRequest
) -> None:
    for image in request.images:
        asset = db.get(Asset, image.asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            raise NotFoundError("asset", image.asset_id)
        if asset.format not in {"jpeg", "png"}:
            raise ValidationFailedError(
                "a 3D generation image must be JPEG or PNG",
                {"asset_id": str(asset.id), "format": asset.format},
            )


def estimate_generation(
    db: Session,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    request: GenerationRequest,
) -> GenerationEstimate:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    _validate_request_assets(db, workspace_id=project.workspace_id, request=request)
    return route_provider(settings, request).estimate


def start_provider_generation(
    db: Session,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    request: GenerationRequest,
    idempotency_key: str | None = None,
) -> tuple[Job, ThreeDGeneration]:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    _validate_request_assets(db, workspace_id=project.workspace_id, request=request)
    decision = route_provider(settings, request)
    provider = decision.provider
    estimate = decision.estimate
    prepared = provider.prepare(request)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=GENERATE_MESH_JOB,
        input={
            "project_id": str(project.id),
            **prepared.payload,
            "provider": provider.name,
            "generation_request": request.model_dump(mode="json"),
            "generation_estimate": estimate.model_dump(mode="json"),
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )
    existing_record = db.get(ThreeDGeneration, job.id)
    if job.input.get("generation_request") != request.model_dump(mode="json"):
        raise ConflictError("Idempotency-Key is already used by another operation")
    if existing_record is not None:
        return job, existing_record
    record = ThreeDGeneration(
        job_id=job.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        provider=estimate.provider,
        provider_model=estimate.model,
        provider_version=estimate.provider_version,
        mode=request.mode.value,
        purpose=request.purpose.value,
        target_format=request.target_format.value,
        request=request.model_dump(mode="json"),
        estimate=estimate.model_dump(mode="json"),
        provider_job_id=prepared.provider_job_id,
    )
    db.add(record)
    db.flush()
    return job, record


def get_provider_generation(
    db: Session, *, user_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Job, ThreeDGeneration]:
    job = jobs.get_job(db, user_id=user_id, job_id=job_id)
    record = db.get(ThreeDGeneration, job.id)
    if record is None:
        raise NotFoundError("3D generation", job_id)
    return job, record


def normalized_status(job: Job) -> GenerationLifecycleStatus:
    if job.status is JobStatus.queued:
        return GenerationLifecycleStatus.queued
    if job.status in {JobStatus.waiting_input, JobStatus.paused}:
        return GenerationLifecycleStatus.preprocessing
    if job.status is JobStatus.canceled:
        return GenerationLifecycleStatus.cancelled
    if job.status is JobStatus.failed:
        return (
            GenerationLifecycleStatus.failed_retryable
            if job.failure_class is FailureClass.retryable
            else GenerationLifecycleStatus.failed_final
        )
    if job.status is JobStatus.succeeded:
        return GenerationLifecycleStatus.ready
    stage = job.stage or ""
    if stage in {"generated", "cleaned"}:
        return GenerationLifecycleStatus.postprocessing
    if stage in {"validating", "validated"}:
        return GenerationLifecycleStatus.validating
    if stage in {"generating", "claimed"}:
        return GenerationLifecycleStatus.generating_geometry
    return GenerationLifecycleStatus.preprocessing


def start_generation(
    db: Session,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    size_mm: float,
    quality: str,
    idempotency_key: str | None = None,
) -> Job:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if settings.mesh_generation_provider == "none":
        raise MeshGenerationNotEnabledError(
            "shape generation from a description is not enabled on this server",
            {"setting": "MESH_GENERATION_PROVIDER"},
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=GENERATE_MESH_JOB,
        input={
            "project_id": str(project.id),
            "prompt": prompt,
            "size_mm": size_mm,
            "quality": quality,
            "provider": settings.mesh_generation_provider,
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )
