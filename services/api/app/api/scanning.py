"""Scan endpoints (E9, F-002): session, resumable frames, finalize, accept."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.engineering.floor_plan import FloorPlan
from app.engineering.room_plan import RoomPlanCapture
from app.models.execution import JobStatus
from app.models.scanning import FrameKind, ScanMode, ScanStatus
from app.services import scanning

# Mirrors ScanMethod/QualityId/TextureSize in packages/contracts/src/create-scenarios.ts.
ScanMethod = Literal["photogrammetry", "gaussian_splat"]
QualityId = Literal["fast", "default", "dense", "raw"]
TextureSize = Literal[1024, 2048, 4096, 8192]


def _quality_id(value: object) -> QualityId:
    normalized = str(value)
    if normalized in {"fast", "default", "dense", "raw"}:
        return cast(QualityId, normalized)
    return "default"


def _texture_size(value: object) -> TextureSize:
    try:
        normalized = int(str(value))
    except (TypeError, ValueError):
        return 2048
    if normalized in {1024, 2048, 4096, 8192}:
        return cast(TextureSize, normalized)
    return 2048

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


class MaskPoint(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ManualMaskStroke(BaseModel):
    mode: Literal["add", "remove"]
    radius: float = Field(ge=0.002, le=0.25)
    points: list[MaskPoint] = Field(min_length=1, max_length=512)


class FrameMaskCorrection(BaseModel):
    sequence_no: int = Field(ge=0, le=100_000)
    strokes: list[ManualMaskStroke] = Field(min_length=1, max_length=64)


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
    mask_corrections: list[FrameMaskCorrection] = Field(default_factory=list, max_length=100)


class AcceptBody(BaseModel):
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)


class ScanCandidateOut(BaseModel):
    key: Literal["balanced", "fast", "detail"]
    title: str
    status: JobStatus
    selected: bool
    quality: QualityId
    texture: TextureSize
    job_id: uuid.UUID
    mesh_asset_id: uuid.UUID | None = None
    report: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ScanCandidateJobsOut(BaseModel):
    jobs: list[JobAccepted]


class SelectScanCandidateBody(BaseModel):
    key: Literal["balanced", "fast", "detail"]


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
    room_shell_asset_id: uuid.UUID | None
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


class RoomShellOut(BaseModel):
    scan_id: uuid.UUID
    available: bool
    asset_id: uuid.UUID | None = None
    source: Literal["apple_roomplan_v2"] | None = None
    reason: str | None = None


class ScanIdeaEvidence(BaseModel):
    floor_area_m2: float = Field(ge=0)
    room_width_mm: float = Field(gt=0)
    room_depth_mm: float = Field(gt=0)
    longest_wall_mm: float = Field(gt=0)
    doors: int = Field(ge=0)
    windows: int = Field(ge=0)


class ScanPrintIdea(BaseModel):
    id: str
    template_id: Literal["organizer", "mounting-plate", "pipe-holder", "phone-stand"]
    title_en: str
    title_ru: str
    reason_en: str
    reason_ru: str
    params: dict[str, float]
    basis: list[Literal["measured_room_plan", "user_label", "general_safe_template"]]


class ScanPrintIdeasOut(BaseModel):
    scan_id: uuid.UUID
    source: Literal["apple_roomplan"]
    recognizes_contents: Literal[False]
    evidence: ScanIdeaEvidence
    ideas: list[ScanPrintIdea]


@router.get("/scans/{scan_id}/room-shell", response_model=RoomShellOut)
def get_room_shell(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> RoomShellOut:
    session = scanning.get_session(db, user_id=principal.user_id, session_id=scan_id)
    if session.room_shell_asset_id is None:
        return RoomShellOut(
            scan_id=session.id,
            available=False,
            reason="room_shell_unavailable",
        )
    return RoomShellOut(
        scan_id=session.id,
        available=True,
        asset_id=session.room_shell_asset_id,
        source="apple_roomplan_v2",
    )


@router.get("/scans/{scan_id}/print-ideas", response_model=ScanPrintIdeasOut)
def get_print_ideas(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ScanPrintIdeasOut:
    return ScanPrintIdeasOut.model_validate(
        scanning.room_print_ideas(db, user_id=principal.user_id, session_id=scan_id)
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
        mask_corrections=[item.model_dump(mode="json") for item in body.mask_corrections],
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/scans/{scan_id}/candidates",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScanCandidateJobsOut,
)
def create_scan_candidates(
    scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> ScanCandidateJobsOut:
    queued = scanning.start_candidates(db, user_id=principal.user_id, session_id=scan_id)
    return ScanCandidateJobsOut(
        jobs=[JobAccepted(job_id=job.id, status=job.status, type=job.type) for job in queued]
    )


@router.get("/scans/{scan_id}/candidates", response_model=list[ScanCandidateOut])
def list_scan_candidates(
    scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[ScanCandidateOut]:
    session, candidate_jobs = scanning.list_candidates(
        db, user_id=principal.user_id, session_id=scan_id
    )
    options = dict(session.processing_options or {})
    base = options.get("candidate_base")
    rows: list[ScanCandidateOut] = []
    if isinstance(base, dict):
        try:
            base_asset_id = uuid.UUID(str(base["mesh_asset_id"]))
            base_job_id = uuid.UUID(str(base["job_id"]))
            base_quality = _quality_id(base.get("quality", "default"))
            base_texture = _texture_size(base.get("texture", 2048))
            rows.append(
                ScanCandidateOut(
                    key="balanced",
                    title="Сбалансированная",
                    status=JobStatus.succeeded,
                    selected=session.mesh_asset_id == base_asset_id,
                    quality=base_quality,
                    texture=base_texture,
                    job_id=base_job_id,
                    mesh_asset_id=base_asset_id,
                    report=base.get("report") if isinstance(base.get("report"), dict) else None,
                )
            )
        except (KeyError, ValueError):
            pass
    for job in candidate_jobs:
        candidate = job.input.get("candidate") or {}
        result = job.result if isinstance(job.result, dict) else {}
        asset_value = result.get("mesh_asset_id")
        try:
            asset_id = uuid.UUID(str(asset_value)) if asset_value else None
        except ValueError:
            asset_id = None
        key = str(candidate.get("key"))
        if key not in {"fast", "detail"}:
            continue
        candidate_key = cast(Literal["fast", "detail"], key)
        rows.append(
            ScanCandidateOut(
                key=candidate_key,
                title=str(candidate.get("title") or candidate_key),
                status=job.status,
                selected=asset_id is not None and session.mesh_asset_id == asset_id,
                quality=_quality_id(candidate.get("quality")),
                texture=_texture_size(candidate.get("texture", 2048)),
                job_id=job.id,
                mesh_asset_id=asset_id,
                report=result.get("report") if isinstance(result.get("report"), dict) else None,
                error=job.error,
            )
        )
    order = {"fast": 0, "balanced": 1, "detail": 2}
    return sorted(rows, key=lambda row: order[row.key])


@router.post("/scans/{scan_id}/candidates/select", response_model=ScanOut)
def select_scan_candidate(
    scan_id: uuid.UUID,
    body: SelectScanCandidateBody,
    db: DbDep,
    principal: PrincipalDep,
) -> ScanOut:
    return ScanOut.model_validate(
        scanning.select_candidate(
            db,
            user_id=principal.user_id,
            session_id=scan_id,
            candidate_key=body.key,
        )
    )


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


@router.post("/scans/{scan_id}/pause", response_model=ScanOut)
def pause_scan(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ScanOut:
    """T-250: ask the reconstruction job to pause. Only photogrammetry/fusion jobs offer a
    checkpoint that skips the reconstruction step on resume — see the job's
    `checkpoint_stage` for which kind this is. Exterior (COLMAP) jobs offer no checkpoint
    at all; photo-room COLMAP jobs have the same boundary. Pausing one before it starts
    running still works (it just never gets
    claimed), but pausing one already running is rejected with 409, since the job cannot
    actually honour the request once it is in flight."""
    return ScanOut.model_validate(scanning.pause(db, user_id=principal.user_id, session_id=scan_id))


@router.post("/scans/{scan_id}/resume", response_model=ScanOut)
def resume_scan(scan_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ScanOut:
    return ScanOut.model_validate(
        scanning.resume(db, user_id=principal.user_id, session_id=scan_id)
    )
