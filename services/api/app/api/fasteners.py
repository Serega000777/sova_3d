"""Metric fastener catalogue, deterministic solid creation and exact-hole fit."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering import fastener as fastener_geometry
from app.engineering import knowledge as kb
from app.services import fasteners

router = APIRouter(tags=["fasteners"])


class FastenerCatalogItem(BaseModel):
    size: str
    nominal_mm: float
    clearance_mm: float
    tap_mm: float
    heat_set_mm: float
    socket_head_diameter_mm: float


class FastenerOut(BaseModel):
    schema_version: Literal[1] = 1
    size: str
    nominal_mm: float
    length_mm: float
    head: fastener_geometry.FastenerHead
    drive: fastener_geometry.FastenerDrive
    head_diameter_mm: float
    head_height_mm: float
    thread_geometry: Literal["smooth_nominal_envelope"]
    drive_recess_modeled: Literal[False]
    geometry_reference: Literal["head_seat_z0"]


class FastenerCreate(BaseModel):
    workspace_id: uuid.UUID
    size: str = Field(pattern=r"^[mM](?:2|2\.5|3|4|5|6|8)$")
    length_mm: float = Field(ge=2, le=200)
    head: fastener_geometry.FastenerHead = "socket_cap"
    drive: fastener_geometry.FastenerDrive = "hex"
    label: str | None = Field(default=None, min_length=1, max_length=200)


class FastenerAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    fastener: FastenerOut


class FastenerFitBody(BaseModel):
    fastener_version_id: uuid.UUID
    hole_operation_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    wanted: Literal["clearance", "sliding", "transition", "press"] = "clearance"
    material_id: str | None = Field(default=None, max_length=64)
    language: Literal["ru", "en"] = "en"


@router.get("/fasteners", response_model=list[FastenerCatalogItem])
def list_fasteners() -> list[FastenerCatalogItem]:
    return [
        FastenerCatalogItem(
            size=item.name,
            nominal_mm=item.nominal_mm,
            clearance_mm=item.clearance_mm,
            tap_mm=item.tap_mm,
            heat_set_mm=item.heat_set_mm,
            socket_head_diameter_mm=item.head_mm,
        )
        for item in kb.FASTENERS.values()
    ]


@router.post("/fasteners", status_code=status.HTTP_202_ACCEPTED, response_model=FastenerAccepted)
def create_fastener(
    body: FastenerCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> FastenerAccepted:
    try:
        spec = fastener_geometry.envelope(
            size=body.size, length_mm=body.length_mm, head=body.head, drive=body.drive
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    job, project_id = fasteners.create(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        spec=spec,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return FastenerAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        fastener=FastenerOut.model_validate(spec.metadata()),
    )


@router.post(
    "/models/{version_id}/fastener-fits",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def fit_fastener(
    version_id: uuid.UUID,
    body: FastenerFitBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = fasteners.enqueue_fit(
        db,
        user_id=principal.user_id,
        target_version_id=version_id,
        fastener_version_id=body.fastener_version_id,
        hole_operation_id=body.hole_operation_id,
        wanted=body.wanted,
        material_id=body.material_id,
        language=body.language,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
