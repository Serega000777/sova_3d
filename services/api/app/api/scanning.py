"""Scan endpoints (E9, F-002): session, resumable frames, finalize, accept."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.engineering.floor_plan import FloorPlan
from app.engineering.room_plan import RoomPlanCapture
from app.models.scanning import FrameKind, ScanMode, ScanStatus
from app.services import scanning

# Mirrors ScanMethod/QualityId/TextureSize in packages/contracts/src/create-scenarios.ts.
ScanMethod = Literal["photogrammetry", "gaussian_splat"]
QualityId = Literal["fast", "default", "dense", "raw"]
TextureSize = Literal[1024, 2048, 4096, 8192]

router = APIRouter(tags=["scanning"])


class ScanCreate(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    mode: ScanMode = ScanMode.rgb
    label: str | None = Field(default=None, max_length=200)
    # Whatever the device reported (T-074): runtime, sensors, permissions.
    capabilities: dict[str, Any] = Field(default_factory=dict)


class FrameCreate(BaseModel):
    asset_id: uuid.UUID
    sequence_no: int = Field(ge=0, le=100_000)
    kind: FrameKind = FrameKind.rgb
    pose: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)


class CaptureStats(BaseModel):
    stats: dict[str, Any]


class RoomPlanCaptureResult(BaseModel):
    floor_plan: FloorPlan
    floor_height_mm: float
    warnings: list[str]


class FinalizeBody(BaseModel):
    """The object's largest dimension, if the user or the device knows it (T-082), plus the
    reconstruction choices from the pre-processing screen (method/quality/texture/mask)."""

    # Exterior structures can legitimately be much larger than the 10 m object-scan cap.
    scale_hint_mm: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    scale_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    method: ScanMethod = "photogrammetry"
    quality: QualityId = "default"
    texture: TextureSize = 2048
    mask_object: bool = False


class AcceptBody(BaseModel):
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)


class FrameOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    sequence_no: int
    kind: FrameKind
    pose: dict[str, Any]
    quality: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None
    status: ScanStatus
    mode: ScanMode
    label: str | None
    capabilities: dict[str, Any]
    capture_stats: dict[str, Any]
    frame_count: int
    processing_options: dict[str, Any]
    job_id: uuid.UUID | None
    mesh_asset_id: uuid.UUID | None
    result_version_id: uuid.UUID | None
    report: dict[str, Any] | None
    scale_hint_mm: Decimal | None
    scale_confidence: Decimal | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.post("/scans", status_code=status.HTTP_201_CREATED, response_model=ScanOut)
def create_scan(
    body: ScanCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> ScanOut:
    session = scanning.create_session(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        mode=body.mode,
        label=body.label,
        capabilities=body.capabilities,
        idempotency_key=idempotency_key,
    )
    return ScanOut.model_validate(session)


class DemoScanBody(BaseModel):
    workspace_id: uuid.UUID
    label: str | None = Field(default=None, max_length=200)


class DemoScanOut(BaseModel):
    scan: ScanOut
    job: JobAccepted


@router.post("/scans/demo", status_code=status.HTTP_202_ACCEPTED, response_model=DemoScanOut)
def demo_scan(body: DemoScanBody, db: DbDep, principal: PrincipalDep) -> DemoScanOut:
    """A simulated scanner run: fragments arrive on the server one by one, then the scan
    finalizes and reconstructs — the whole Scanner flow without a device."""
    session, job = scanning.start_demo(
        db, user_id=principal.user_id, workspace_id=body.workspace_id, label=body.label
    )
    return DemoScanOut(
        scan=ScanOut.model_validate(session),
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
    )


@router.get("/scans", response_model=list[ScanOut])
def list_scans(
    db: DbDep,
    principal: PrincipalDep,
    workspace_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ScanOut]:
    rows = scanning.list_sessions(
        db, user_id=principal.user_id, workspace_id=workspace_id, limit=limit
    )
    return [ScanOut.model_validate(row) for row in rows]


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ScanOut:
    return ScanOut.model_validate(
        scanning.get_session(db, user_id=principal.user_id, session_id=scan_id)
    )


@router.get("/scans/{scan_id}/frames", response_model=list[FrameOut])
def list_frames(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[FrameOut]:
    session = scanning.get_session(db, user_id=principal.user_id, session_id=scan_id)
    return [FrameOut.model_validate(frame) for frame in scanning.list_frames(db, session)]


@router.post(
    "/scans/{scan_id}/frames", status_code=status.HTTP_201_CREATED, response_model=FrameOut
)
def add_frame(
    scan_id: uuid.UUID, body: FrameCreate, db: DbDep, principal: PrincipalDep
) -> FrameOut:
    frame = scanning.add_frame(
        db,
        user_id=principal.user_id,
        session_id=scan_id,
        asset_id=body.asset_id,
        sequence_no=body.sequence_no,
        kind=body.kind,
        pose=body.pose,
        quality=body.quality,
    )
    return FrameOut.model_validate(frame)


@router.patch("/scans/{scan_id}/capture-stats", response_model=ScanOut)
def update_capture_stats(
    scan_id: uuid.UUID, body: CaptureStats, db: DbDep, principal: PrincipalDep
) -> ScanOut:
    session = scanning.update_capture_stats(
        db, user_id=principal.user_id, session_id=scan_id, stats=body.stats
    )
    return ScanOut.model_validate(session)


@router.put("/scans/{scan_id}/room-plan", response_model=RoomPlanCaptureResult)
def set_room_plan(
    scan_id: uuid.UUID,
    body: RoomPlanCapture,
    db: DbDep,
    principal: PrincipalDep,
) -> RoomPlanCaptureResult:
    converted = scanning.set_room_plan(
        db,
        user_id=principal.user_id,
        session_id=scan_id,
        capture=body,
    )
    return RoomPlanCaptureResult(
        floor_plan=converted.plan,
        floor_height_mm=converted.floor_height_mm,
        warnings=list(converted.warnings),
    )


@router.post(
    "/scans/{scan_id}/finalize", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted
)
def finalize_scan(
    scan_id: uuid.UUID,
    body: FinalizeBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = scanning.finalize(
        db,
        user_id=principal.user_id,
        session_id=scan_id,
        scale_hint_mm=body.scale_hint_mm,
        scale_confidence=body.scale_confidence,
        method=body.method,
        quality=body.quality,
        texture=body.texture,
        mask_object=body.mask_object,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post("/scans/{scan_id}/accept", response_model=ScanOut)
def accept_scan(
    scan_id: uuid.UUID, body: AcceptBody, db: DbDep, principal: PrincipalDep
) -> ScanOut:
    session = scanning.accept(
        db,
        user_id=principal.user_id,
        session_id=scan_id,
        project_id=body.project_id,
        label=body.label,
    )
    return ScanOut.model_validate(session)


@router.post("/scans/{scan_id}/cancel", response_model=ScanOut)
def cancel_scan(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ScanOut:
    return ScanOut.model_validate(
        scanning.cancel(db, user_id=principal.user_id, session_id=scan_id)
    )
