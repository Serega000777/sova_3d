"""Scan sessions (E9, F-002): capture -> resumable upload -> reconstruction -> accept.

A session survives a dropped connection: frames are registered one by one under the
client's own sequence number, so re-sending one is a no-op rather than a duplicate
(T-078). Finalizing queues the reconstruction job (T-079); accepting the result turns
the reconstructed mesh into a project version like any other model.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.engineering.floor_plan import FloorPlan
from app.engineering.room_plan import RoomPlanCapture, RoomPlanConversion, floor_plan_from_room_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.scanning import FrameKind, ScanFrame, ScanMode, ScanSession, ScanStatus
from app.models.versioning import Asset, AssetRole
from app.services import jobs, projects
from app.services.authz import require_workspace_role

RECONSTRUCT_JOB = "reconstruct_scan"
DEMO_SCAN_JOB = "demo_scan"  # a simulated turntable scanner run on the server (F-082)
MIN_FRAMES = 12
MIN_SCANNER_FRAMES = 1  # a scanner may hand over one fused mesh (F-082)
MAX_FRAMES = 600
FRAGMENT_FORMATS = ("ply", "stl", "obj", "usdz")
EXTERIOR_SECTIONS = ("front", "right", "back", "left")
MIN_EXTERIOR_SECTION_FRAMES = 8


def min_frames(session: ScanSession) -> int:
    return MIN_SCANNER_FRAMES if session.mode is ScanMode.scanner else MIN_FRAMES


OPEN_STATES = (ScanStatus.capturing, ScanStatus.uploading)


def create_session(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    mode: ScanMode = ScanMode.rgb,
    label: str | None = None,
    capabilities: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ScanSession:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if idempotency_key:
        existing = db.scalar(
            sa.select(ScanSession).where(
                ScanSession.workspace_id == workspace_id,
                ScanSession.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
    if project_id is not None:
        projects.get_project(db, user_id=user_id, project_id=project_id)  # authz + existence

    session = ScanSession(
        workspace_id=workspace_id,
        project_id=project_id,
        created_by=user_id,
        idempotency_key=idempotency_key,
        mode=mode,
        label=label,
        capabilities=capabilities or {},
    )
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> ScanSession:
    session = db.get(ScanSession, session_id)
    if session is None:
        raise NotFoundError("scan_session", session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.viewer)
    return session


def list_sessions(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, limit: int = 50
) -> list[ScanSession]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    rows = db.scalars(
        sa.select(ScanSession)
        .where(ScanSession.workspace_id == workspace_id)
        .order_by(ScanSession.created_at.desc())
        .limit(limit)
    ).all()
    return list(rows)


def list_frames(db: Session, session: ScanSession) -> list[ScanFrame]:
    rows = db.scalars(
        sa.select(ScanFrame)
        .where(ScanFrame.scan_session_id == session.id)
        .order_by(ScanFrame.sequence_no, ScanFrame.kind)
    ).all()
    return list(rows)


def add_frame(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    asset_id: uuid.UUID,
    sequence_no: int,
    kind: FrameKind = FrameKind.rgb,
    pose: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> ScanFrame:
    """Register an already-uploaded image as a frame. Re-sending one frame is a no-op."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status not in OPEN_STATES:
        raise ConflictError(
            "this scan is no longer capturing",
            {"status": session.status.value},
        )
    if session.frame_count >= MAX_FRAMES:
        raise ValidationFailedError(
            f"a scan takes at most {MAX_FRAMES} frames", {"frame_count": session.frame_count}
        )

    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != session.workspace_id:
        raise NotFoundError("asset", asset_id)
    if kind in (FrameKind.pointcloud, FrameKind.mesh):
        if asset.format not in FRAGMENT_FORMATS:
            raise ValidationFailedError(
                "a scanner fragment must be a PLY, STL or OBJ file",
                {"asset_id": str(asset_id), "format": asset.format},
            )
    elif asset.format not in ("jpeg", "png"):
        raise ValidationFailedError(
            "a scan frame must be an image", {"asset_id": str(asset_id), "format": asset.format}
        )

    existing = db.scalar(
        sa.select(ScanFrame).where(
            ScanFrame.scan_session_id == session.id,
            ScanFrame.sequence_no == sequence_no,
            ScanFrame.kind == kind,
        )
    )
    if existing is not None:
        if existing.asset_id != asset_id:
            raise ConflictError(
                "that frame number already holds a different image",
                {"sequence_no": sequence_no, "kind": kind.value},
            )
        return existing  # resumed upload re-sent a frame it had already delivered

    frame = ScanFrame(
        scan_session_id=session.id,
        asset_id=asset_id,
        sequence_no=sequence_no,
        kind=kind,
        pose=pose or {},
        quality=quality or {},
    )
    db.add(frame)
    session.status = ScanStatus.uploading
    db.flush()
    db.refresh(session)  # frame_count is maintained by a trigger
    return frame


def update_capture_stats(
    db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID, stats: dict[str, Any]
) -> ScanSession:
    """Guided-capture progress from the client (T-075): coverage, blur, hints shown."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if "room_plan" in stats:
        raise ValidationFailedError(
            "room_plan is reserved; use the validated RoomPlan geometry endpoint"
        )
    session.capture_stats = {**session.capture_stats, **stats}
    db.flush()
    return session


def set_room_plan(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    capture: RoomPlanCapture,
) -> RoomPlanConversion:
    """Attach one validated Apple RoomPlan room to an open metric scanner session."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status not in OPEN_STATES:
        raise ConflictError(
            "RoomPlan geometry must be attached before reconstruction starts",
            {"status": session.status.value},
        )
    if session.mode is not ScanMode.scanner:
        raise ValidationFailedError("RoomPlan geometry requires a metric scanner session")
    try:
        converted = floor_plan_from_room_plan(
            capture,
            plan_id=f"scan-{session.id}-roomplan",
            name=session.label or "RoomPlan room",
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    session.capture_stats = {
        **session.capture_stats,
        "room_plan": {
            "schema_version": 1,
            "source": "apple_roomplan",
            "room_id": capture.room_id,
            "floor_height_mm": converted.floor_height_mm,
            "warnings": list(converted.warnings),
            "floor_plan": converted.plan.model_dump(mode="json"),
        },
    }
    db.flush()
    return converted


def finalize(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    scale_hint_mm: Decimal | None = None,
    scale_confidence: Decimal | None = None,
    method: str = "photogrammetry",
    quality: str = "default",
    texture: int = 2048,
    mask_object: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    """T-079: close capture and queue the reconstruction."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)

    if session.status is ScanStatus.reconstructing and session.job_id is not None:
        job = db.get(Job, session.job_id)
        if job is not None:
            return job  # finalize is idempotent while the job runs
    if session.status not in OPEN_STATES:
        raise ConflictError("this scan has already been finalized", {"status": session.status})
    required = min_frames(session)
    if session.frame_count < required:
        raise ValidationFailedError(
            f"a scan needs at least {required} frame(s) to reconstruct",
            {"frame_count": session.frame_count, "required": required},
        )

    # T-232: a building exterior is not one generic turntable sweep. Prove that actual
    # registered frames cover every facade section and carry at least an orientation pose.
    # RoomPlan support is deliberately not treated as exterior metric depth.
    is_exterior = (session.capabilities or {}).get("subject") == "exterior"
    if is_exterior:
        frames = list_frames(db, session)
        section_counts = {
            section: sum(
                1 for frame in frames if (frame.pose or {}).get("exterior_section") == section
            )
            for section in EXTERIOR_SECTIONS
        }
        missing = [
            section
            for section, count in section_counts.items()
            if count < MIN_EXTERIOR_SECTION_FRAMES
        ]
        if missing:
            raise ValidationFailedError(
                "an exterior scan needs overlapping frames for every facade section",
                {"missing_sections": missing, "section_counts": section_counts},
            )
        pose_missing = sum(1 for frame in frames if "azimuth_deg" not in (frame.pose or {}))
        if pose_missing:
            raise ValidationFailedError(
                "every exterior frame needs a camera orientation",
                {"frames_without_orientation": pose_missing},
            )
        trustworthy_metric = (session.capabilities or {}).get("metric_scale") in {
            "depth",
            "ar_pose",
            "scanner",
        }
        if scale_hint_mm is None and not trustworthy_metric:
            raise ValidationFailedError(
                "an exterior scan needs a measured maximum dimension before it can be metric",
                {"required": "scale_hint_mm", "metric_scale": "unavailable"},
            )

    if scale_hint_mm is not None:
        if scale_hint_mm <= 0:
            raise ValidationFailedError("scale_hint_mm must be positive")
        if not is_exterior and scale_hint_mm > 10_000:
            raise ValidationFailedError(
                "scale_hint_mm exceeds the 10 m object-scan limit",
                {"scale_hint_mm": str(scale_hint_mm), "maximum": 10_000},
            )
        session.scale_hint_mm = scale_hint_mm
    if scale_confidence is not None:
        session.scale_confidence = scale_confidence

    session.processing_options = {
        "method": method,
        "quality": quality,
        "texture": texture,
        "mask_object": mask_object,
    }

    job = jobs.enqueue(
        db,
        workspace_id=session.workspace_id,
        job_type=RECONSTRUCT_JOB,
        input={"scan_session_id": str(session.id)},
        created_by=user_id,
        project_id=session.project_id,
        idempotency_key=idempotency_key,
    )
    session.status = ScanStatus.reconstructing
    session.job_id = job.id
    session.error = None
    db.flush()
    return job


def accept(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    label: str | None = None,
) -> ScanSession:
    """T-084: the user keeps the reconstruction — it becomes a version in a project."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status is ScanStatus.accepted and session.result_version_id is not None:
        return session
    if session.status is not ScanStatus.ready or session.mesh_asset_id is None:
        raise ConflictError(
            "this scan has no reconstruction to accept", {"status": session.status.value}
        )

    target = project_id or session.project_id
    if target is None:
        raise ValidationFailedError("project_id is required: this scan has no project yet")
    project = projects.get_project(db, user_id=user_id, project_id=target)

    provenance: dict[str, Any] = {
        "operation": "scan",
        "scan_session_id": str(session.id),
        "job_id": str(session.job_id) if session.job_id else None,
        "frames": session.frame_count,
        "mode": session.mode.value,
        "report": session.report or {},
    }
    room_plan = (session.capture_stats or {}).get("room_plan")
    if isinstance(room_plan, dict) and isinstance(room_plan.get("floor_plan"), dict):
        try:
            plan = FloorPlan.model_validate(room_plan["floor_plan"])
        except ValueError:
            plan = None
        if plan is not None:
            provenance["floor_plan"] = plan.model_dump(mode="json")
            provenance["room_plan"] = {
                key: value for key, value in room_plan.items() if key != "floor_plan"
            }

    version = projects.create_version_internal(
        db,
        project_id=project.id,
        parent_version_id=project.head_version_id,
        label=label or session.label or "Scan",
        provenance=provenance,
        assets={AssetRole.model: session.mesh_asset_id},
        finalize=True,
        created_by=user_id,
    )
    session.project_id = project.id
    session.result_version_id = version.id
    session.status = ScanStatus.accepted
    db.flush()
    return session


def cancel(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> ScanSession:
    """T-084 retry: abandon this attempt and stop every queued/running job it owns.

    The frames stay for diagnosis.  Cancellation is cooperative for a running worker and
    immediate for queued work, using the same job state machine as ``POST /jobs/{id}/cancel``.
    """
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status is ScanStatus.accepted:
        raise ConflictError("an accepted scan cannot be canceled", {"status": session.status.value})
    if session.status is ScanStatus.canceled:
        return session

    job_ids: set[uuid.UUID] = set()
    if session.job_id is not None:
        job_ids.add(session.job_id)
    demo_job_id = (session.capture_stats or {}).get("demo_job_id")
    if demo_job_id:
        try:
            job_ids.add(uuid.UUID(str(demo_job_id)))
        except ValueError:
            pass
    for job_id in job_ids:
        job = db.get(Job, job_id)
        if job is not None and jobs.is_active(job):
            jobs.request_cancel(db, user_id=user_id, job_id=job.id)

    session.status = ScanStatus.canceled
    db.flush()
    return session


def start_demo(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, label: str | None = None
) -> tuple[ScanSession, Job]:
    """A scanner session fed by the server's simulated turntable: the Scanner section can be
    watched working before any device is plugged in."""
    session = create_session(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        mode=ScanMode.scanner,
        label=label or "Demo scan",
        capabilities={
            "device": {
                "vendor": "Physical AI",
                "model": "Simulated turntable",
                "driver": "simulated",
                "accuracy_mm": 0.05,
                "turntable": True,
            }
        },
    )
    job = jobs.enqueue(
        db,
        workspace_id=workspace_id,
        job_type=DEMO_SCAN_JOB,
        input={"scan_session_id": str(session.id)},
        created_by=user_id,
    )
    session.capture_stats = {"demo_job_id": str(job.id)}
    db.flush()
    return session, job
