"""Scan sessions (E9, F-002): capture -> resumable upload -> reconstruction -> accept.

A session survives a dropped connection: frames are registered one by one under the
client's own sequence number, so re-sending one is a no-op rather than a duplicate
(T-078). Finalizing queues the reconstruction job (T-079); accepting the result turns
the reconstructed mesh into a project version like any other model.
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.engineering.floor_plan import FloorPlan
from app.engineering.room_plan import RoomPlanCapture, RoomPlanConversion, floor_plan_from_room_plan
from app.engineering.room_shell import room_shell_spec
from app.models.core import WorkspaceRole
from app.models.execution import Job, JobStatus
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
PHOTO_ROOM_CAPTURE_SOURCE = "room_photogrammetry_v1"
ROOM_PHOTO_SECTIONS = ("front", "right", "back", "left")
MIN_ROOM_PHOTO_SECTION_FRAMES = 8
MAX_ROOM_PHOTO_SPAN_MM = Decimal("100000")
ROOM_PHOTO_SCALE_CONFIDENCE = Decimal("0.6")
BROKEN_PART_CAPTURE_PLAN = "broken_part_sections_v1"
BROKEN_PART_SECTION_TARGETS = {"whole": 8, "fracture": 4, "interior": 4}
SCAN_CANDIDATE_SPECS: tuple[dict[str, Any], ...] = (
    {"key": "fast", "title": "Быстрая", "quality": "fast", "texture": 1024},
    {"key": "detail", "title": "Детальная", "quality": "dense", "texture": 4096},
)


def _polygon_area_mm2(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            point[0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * point[1]
            for index, point in enumerate(points)
        )
        / 2
    )


def room_print_ideas(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
    """F-021: bounded printable ideas based only on validated metric RoomPlan geometry.

    This deliberately does not claim to recognize furniture or other room contents.  Every
    returned action points at an existing, buildable template and every parameter stays in
    that template's public range.
    """
    session = get_session(db, user_id=user_id, session_id=session_id)
    room_plan = (session.capture_stats or {}).get("room_plan")
    if not isinstance(room_plan, dict) or not isinstance(room_plan.get("floor_plan"), dict):
        raise ValidationFailedError(
            "print ideas require validated metric RoomPlan geometry",
            {"scan_id": str(session.id), "required_source": "apple_roomplan"},
        )
    try:
        plan = FloorPlan.model_validate(room_plan["floor_plan"])
    except ValueError as exc:
        raise ValidationFailedError(
            "the stored RoomPlan geometry is invalid", {"scan_id": str(session.id)}
        ) from exc

    points = [point for room in plan.rooms for point in room.outline]
    if not points:
        points = [point for wall in plan.walls for point in (wall.a, wall.b)]
    if not points or not plan.walls:
        raise ValidationFailedError(
            "print ideas require a measured room outline", {"scan_id": str(session.id)}
        )
    width_mm = max(point[0] for point in points) - min(point[0] for point in points)
    depth_mm = max(point[1] for point in points) - min(point[1] for point in points)
    floor_area_m2 = sum(_polygon_area_mm2(room.outline) for room in plan.rooms) / 1_000_000
    longest_wall_mm = max(math.dist(wall.a, wall.b) for wall in plan.walls)
    doors = sum(opening.kind == "door" for opening in plan.openings)
    windows = sum(opening.kind == "window" for opening in plan.openings)
    evidence = {
        "floor_area_m2": round(floor_area_m2, 3),
        "room_width_mm": round(width_mm, 1),
        "room_depth_mm": round(depth_mm, 1),
        "longest_wall_mm": round(longest_wall_mm, 1),
        "doors": doors,
        "windows": windows,
    }

    short_side = min(width_mm, depth_mm)
    organizer_width = round(max(80, min(300, short_side * 0.08)))
    organizer_depth = round(max(40, min(180, organizer_width * 0.55)))
    compartments = max(2, min(8, organizer_width // 40))
    ideas: list[dict[str, Any]] = [
        {
            "id": "measured-organizer",
            "template_id": "organizer",
            "title_en": "Room organizer",
            "title_ru": "Органайзер для помещения",
            "reason_en": (
                f"Sized conservatively from the measured {width_mm / 1000:.2f} × "
                f"{depth_mm / 1000:.2f} m room bounds."
            ),
            "reason_ru": (
                f"Консервативный размер рассчитан по измеренному габариту помещения "
                f"{width_mm / 1000:.2f} × {depth_mm / 1000:.2f} м."
            ),
            "params": {
                "w": float(organizer_width),
                "d": float(organizer_depth),
                "h": 50.0,
                "n": float(compartments),
            },
            "basis": ["measured_room_plan"],
        },
        {
            "id": "measured-mounting-plate",
            "template_id": "mounting-plate",
            "title_en": "Mounting plate",
            "title_ru": "Монтажная пластина",
            "reason_en": (
                f"The longest measured wall is {longest_wall_mm / 1000:.2f} m. "
                "Choose and verify the exact mounting location before printing."
            ),
            "reason_ru": (
                f"Самая длинная измеренная стена — {longest_wall_mm / 1000:.2f} м. "
                "Перед печатью выберите и проверьте точное место крепления."
            ),
            "params": {"w": 120.0, "d": 50.0, "h": 4.0, "n": 4.0, "m": 4.0},
            "basis": ["measured_room_plan"],
        },
    ]
    label = (session.label or "").casefold()
    workshop = any(token in label for token in ("garage", "workshop", "гараж", "мастерск"))
    ideas.append(
        {
            "id": "label-pipe-holder" if workshop else "general-phone-stand",
            "template_id": "pipe-holder" if workshop else "phone-stand",
            "title_en": "Pipe holder" if workshop else "Phone stand",
            "title_ru": "Держатель для трубы" if workshop else "Подставка для телефона",
            "reason_en": (
                "Suggested because the user named this scan as a garage or workshop; "
                "the pipe diameter still needs confirmation."
                if workshop
                else "A general-purpose printable idea; the scan does not identify room contents."
            ),
            "reason_ru": (
                "Предложено потому, что пользователь назвал скан гаражом или мастерской; "
                "диаметр трубы ещё нужно подтвердить."
                if workshop
                else "Универсальная идея для печати; скан не распознаёт содержимое помещения."
            ),
            "params": {"pipe": 32.0} if workshop else {},
            "basis": ["user_label"] if workshop else ["general_safe_template"],
        }
    )
    return {
        "scan_id": session.id,
        "source": "apple_roomplan",
        "recognizes_contents": False,
        "evidence": evidence,
        "ideas": ideas,
    }


def is_photo_room(session: ScanSession) -> bool:
    capabilities = session.capabilities or {}
    return (
        capabilities.get("capture_source") == PHOTO_ROOM_CAPTURE_SOURCE
        and capabilities.get("subject") in {"room", "home"}
        and session.mode is ScanMode.rgb
    )


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
        shell = room_shell_spec(capture, converted)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    session.capture_stats = {
        **session.capture_stats,
        "room_plan": {
            "schema_version": capture.schema_version,
            "source": "apple_roomplan",
            "room_id": capture.room_id,
            "floor_height_mm": converted.floor_height_mm,
            "warnings": list(converted.warnings),
            "floor_plan": converted.plan.model_dump(mode="json"),
            "room_shell": shell.to_dict() if shell is not None else None,
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
    mask_corrections: list[dict[str, Any]] | None = None,
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
    photo_room = is_photo_room(session)
    broken_part = (session.capabilities or {}).get("capture_plan") == BROKEN_PART_CAPTURE_PLAN
    if broken_part and (
        session.mode is not ScanMode.rgb or (session.capabilities or {}).get("subject") != "object"
    ):
        raise ValidationFailedError(
            "broken_part_sections_v1 requires an RGB object session",
            {"mode": session.mode.value, "subject": (session.capabilities or {}).get("subject")},
        )
    if (session.capabilities or {}).get(
        "capture_source"
    ) == PHOTO_ROOM_CAPTURE_SOURCE and not photo_room:
        raise ValidationFailedError(
            "room_photogrammetry_v1 requires an RGB room or home session",
            {
                "mode": session.mode.value,
                "subject": (session.capabilities or {}).get("subject"),
            },
        )
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

    if photo_room:
        frames = [frame for frame in list_frames(db, session) if frame.kind is FrameKind.rgb]
        section_counts = {
            section: sum(1 for frame in frames if (frame.pose or {}).get("room_section") == section)
            for section in ROOM_PHOTO_SECTIONS
        }
        missing = [
            section
            for section, count in section_counts.items()
            if count < MIN_ROOM_PHOTO_SECTION_FRAMES
        ]
        if missing:
            raise ValidationFailedError(
                "a photo-room scan needs overlapping frames for every wall section",
                {"missing_sections": missing, "section_counts": section_counts},
            )
        pose_missing = sum(1 for frame in frames if "azimuth_deg" not in (frame.pose or {}))
        if pose_missing:
            raise ValidationFailedError(
                "every photo-room frame needs a camera orientation",
                {"frames_without_orientation": pose_missing},
            )
        if scale_hint_mm is None:
            raise ValidationFailedError(
                "a photo-room scan needs a measured maximum room span",
                {"required": "scale_hint_mm", "metric_scale": "user_measured_span"},
            )

    if broken_part:
        frames = [frame for frame in list_frames(db, session) if frame.kind is FrameKind.rgb]
        section_counts = {
            section: sum(
                1 for frame in frames if (frame.pose or {}).get("broken_part_section") == section
            )
            for section in BROKEN_PART_SECTION_TARGETS
        }
        missing = [
            section
            for section, target in BROKEN_PART_SECTION_TARGETS.items()
            if section_counts[section] < target
        ]
        if missing:
            raise ValidationFailedError(
                "a broken-part scan needs whole, fracture and interior frame coverage",
                {"missing_sections": missing, "section_counts": section_counts},
            )
        pose_missing = sum(1 for frame in frames if "azimuth_deg" not in (frame.pose or {}))
        if pose_missing:
            raise ValidationFailedError(
                "every broken-part frame needs a camera orientation",
                {"frames_without_orientation": pose_missing},
            )
        session.capture_stats = {
            **(session.capture_stats or {}),
            "broken_part": {
                "capture_plan": BROKEN_PART_CAPTURE_PLAN,
                "section_counts": section_counts,
                "evidence": "user_labelled_capture_sections",
                "damage_detection": "not_performed",
                "hidden_geometry": "not_proven",
            },
        }

    if scale_hint_mm is not None:
        if scale_hint_mm <= 0:
            raise ValidationFailedError("scale_hint_mm must be positive")
        if not is_exterior and not photo_room and scale_hint_mm > 10_000:
            raise ValidationFailedError(
                "scale_hint_mm exceeds the 10 m object-scan limit",
                {"scale_hint_mm": str(scale_hint_mm), "maximum": 10_000},
            )
        if photo_room and scale_hint_mm > MAX_ROOM_PHOTO_SPAN_MM:
            raise ValidationFailedError(
                "scale_hint_mm exceeds the 100 m photo-room limit",
                {
                    "scale_hint_mm": str(scale_hint_mm),
                    "maximum": str(MAX_ROOM_PHOTO_SPAN_MM),
                },
            )
        session.scale_hint_mm = scale_hint_mm
    if photo_room:
        # A client cannot promote a user-entered tape measurement to sensor confidence.
        session.scale_confidence = ROOM_PHOTO_SCALE_CONFIDENCE
    elif scale_confidence is not None:
        session.scale_confidence = scale_confidence

    corrections = list(mask_corrections or [])
    if corrections:
        if not mask_object:
            raise ValidationFailedError("manual mask corrections require mask_object=true")
        if (
            session.mode is ScanMode.scanner
            or (session.capabilities or {}).get("subject") != "object"
        ):
            raise ValidationFailedError(
                "manual mask corrections are only valid for RGB object scans"
            )
        rgb_sequences = {
            frame.sequence_no for frame in list_frames(db, session) if frame.kind is FrameKind.rgb
        }
        correction_sequences = [int(item["sequence_no"]) for item in corrections]
        if len(set(correction_sequences)) != len(correction_sequences):
            raise ValidationFailedError(
                "manual mask corrections must use unique frame sequence numbers"
            )
        missing_sequences = sorted(set(correction_sequences) - rgb_sequences)
        if missing_sequences:
            raise ValidationFailedError(
                "manual mask correction targets an unavailable RGB frame",
                {"sequence_nos": missing_sequences},
            )
        total_points = sum(
            len(stroke.get("points", []))
            for correction in corrections
            for stroke in correction.get("strokes", [])
        )
        if total_points > 20_000:
            raise ValidationFailedError(
                "manual mask corrections exceed the point budget",
                {"points": total_points, "maximum": 20_000},
            )

    session.processing_options = {
        "method": method,
        "quality": quality,
        "texture": texture,
        "mask_object": mask_object,
        "mask_corrections": corrections,
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


def _candidate_jobs(db: Session, session: ScanSession) -> list[Job]:
    rows = db.scalars(
        sa.select(Job)
        .where(Job.workspace_id == session.workspace_id, Job.type == RECONSTRUCT_JOB)
        .order_by(Job.created_at, Job.id)
    ).all()
    return [
        job
        for job in rows
        if str((job.input or {}).get("scan_session_id")) == str(session.id)
        and isinstance((job.input or {}).get("candidate"), dict)
    ]


def start_candidates(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> list[Job]:
    """Queue two alternate quality reconstructions from the exact same captured frames.

    The already-ready reconstruction is the balanced candidate. Alternatives keep their
    output on their own jobs until the user explicitly selects one, so parallel workers
    cannot race to overwrite the scan result.
    """
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if (
        session.status is not ScanStatus.ready
        or session.mesh_asset_id is None
        or session.job_id is None
    ):
        raise ConflictError(
            "this scan has no ready reconstruction to compare",
            {"status": session.status.value},
        )
    if session.mode is not ScanMode.rgb or (session.capabilities or {}).get("subject") != "object":
        raise ValidationFailedError("reconstruction candidates are supported for RGB object scans")

    options = dict(session.processing_options or {})
    if options.get("method", "photogrammetry") != "photogrammetry":
        raise ValidationFailedError("reconstruction candidates require photogrammetry")
    if not isinstance(options.get("candidate_base"), dict):
        options["candidate_base"] = {
            "job_id": str(session.job_id),
            "mesh_asset_id": str(session.mesh_asset_id),
            "report": dict(session.report or {}),
            "quality": str(options.get("quality", "default")),
            "texture": int(options.get("texture", 2048)),
        }
        session.processing_options = options

    existing = {
        str((job.input.get("candidate") or {}).get("key")): job
        for job in _candidate_jobs(db, session)
    }
    made: list[Job] = []
    for spec in SCAN_CANDIDATE_SPECS:
        current = existing.get(str(spec["key"]))
        if current is not None:
            made.append(current)
            continue
        candidate_options = {
            **{key: value for key, value in options.items() if key != "candidate_base"},
            "method": "photogrammetry",
            "quality": spec["quality"],
            "texture": spec["texture"],
        }
        made.append(
            jobs.enqueue(
                db,
                workspace_id=session.workspace_id,
                job_type=RECONSTRUCT_JOB,
                input={
                    "scan_session_id": str(session.id),
                    "candidate": {**spec, "options": candidate_options},
                },
                created_by=user_id,
                project_id=session.project_id,
                idempotency_key=f"scan-candidate:{session.id}:{spec['key']}",
            )
        )
    db.flush()
    return made


def list_candidates(
    db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[ScanSession, list[Job]]:
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.viewer)
    return session, _candidate_jobs(db, session)


def select_candidate(
    db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID, candidate_key: str
) -> ScanSession:
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status is not ScanStatus.ready:
        raise ConflictError(
            "only a ready scan can change candidate", {"status": session.status.value}
        )
    base = (session.processing_options or {}).get("candidate_base")
    if candidate_key == "balanced":
        if not isinstance(base, dict):
            raise ConflictError("balanced candidate was not preserved")
        source = base
    else:
        job = next(
            (
                item
                for item in _candidate_jobs(db, session)
                if str((item.input.get("candidate") or {}).get("key")) == candidate_key
            ),
            None,
        )
        if job is None:
            raise NotFoundError("scan_candidate", candidate_key)
        if job.status is not JobStatus.succeeded or not isinstance(job.result, dict):
            raise ConflictError(
                "this reconstruction candidate is not ready", {"status": job.status.value}
            )
        source = {**job.result, "job_id": str(job.id)}
    try:
        asset_id = uuid.UUID(str(source["mesh_asset_id"]))
        job_id = uuid.UUID(str(source["job_id"]))
    except (KeyError, ValueError) as exc:
        raise ConflictError("candidate result is incomplete") from exc
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != session.workspace_id:
        raise ConflictError("candidate mesh is unavailable")
    report = source.get("report")
    if not isinstance(report, dict):
        raise ConflictError("candidate report is unavailable")
    session.mesh_asset_id = asset.id
    session.job_id = job_id
    session.report = report
    session.error = None
    db.flush()
    return session


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
    broken_part = (session.capture_stats or {}).get("broken_part")
    if isinstance(broken_part, dict):
        provenance["broken_part_capture"] = dict(broken_part)
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
        assets={
            AssetRole.model: session.mesh_asset_id,
            **(
                {AssetRole.room_shell: session.room_shell_asset_id}
                if session.room_shell_asset_id is not None
                else {}
            ),
        },
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


def pause(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> ScanSession:
    """T-250: ask the reconstruction job to pause at its next checkpoint.

    Queued/not-yet-started work pauses immediately, so the session follows suit right
    away. A running job only pauses the session once the handler itself reaches a
    checkpoint and writes ``ScanStatus.paused`` (see ``handle_reconstruct``) — never
    here, which would otherwise claim "paused" while the worker is still computing.

    Exterior (COLMAP) jobs offer no pausable checkpoint at all once they are running —
    ``handle_reconstruct`` only calls the plain, non-pausable ``progress()`` for that
    branch (see its module docstring) — so a pause requested here would be accepted and
    then never actually consumed, leaving ``pause_requested`` stuck true on a job that
    quietly runs to completion anyway. Reject it up front instead, same as the task's
    own fail-closed requirement for an unsupported pause.
    """
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status is not ScanStatus.reconstructing:
        raise ConflictError(
            "only a reconstructing scan can be paused", {"status": session.status.value}
        )
    if session.job_id is None:
        raise ConflictError("this scan has no reconstruction job", {"status": session.status.value})
    job = db.get(Job, session.job_id)
    if job is None:
        raise NotFoundError("job", session.job_id)
    is_colmap = (session.capabilities or {}).get("subject") == "exterior" or is_photo_room(session)
    if is_colmap and job.status is JobStatus.running:
        raise ConflictError(
            "COLMAP scans cannot be paused once reconstruction has started "
            "(no resumable checkpoint exists for this mode)",
            {"status": session.status.value},
        )
    updated = jobs.request_pause(db, user_id=user_id, job_id=job.id)
    if updated.status is JobStatus.paused:  # was queued/waiting_input: took effect now
        session.status = ScanStatus.paused
        db.flush()
    db.refresh(session)
    return session


def resume(db: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> ScanSession:
    """T-250: requeue the paused reconstruction job. The handler reads its own checkpoint
    and decides how much earlier work it can skip; nothing here guesses on its behalf."""
    session = get_session(db, user_id=user_id, session_id=session_id)
    require_workspace_role(db, user_id, session.workspace_id, WorkspaceRole.editor)
    if session.status is not ScanStatus.paused:
        raise ConflictError("this scan is not paused", {"status": session.status.value})
    if session.job_id is None:
        raise ConflictError("this scan has no reconstruction job", {"status": session.status.value})
    jobs.request_resume(db, user_id=user_id, job_id=session.job_id)
    session.status = ScanStatus.reconstructing
    db.flush()
    db.refresh(session)
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
