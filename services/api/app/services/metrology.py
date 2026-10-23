"""Post-print metric scan comparison (F-043)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.scanning import ScanMode, ScanSession, ScanStatus
from app.services import jobs, projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.authz import require_workspace_role

PHYSICAL_COMPARE_JOB = "physical_compare"


def enqueue_comparison(
    db: Session,
    *,
    user_id: uuid.UUID,
    design_version_id: uuid.UUID,
    scan_version_id: uuid.UUID,
    tolerance_mm: float,
    samples: int,
    idempotency_key: str | None = None,
) -> Job:
    design = projects.get_version(db, user_id=user_id, version_id=design_version_id)
    scan = projects.get_version(db, user_id=user_id, version_id=scan_version_id)
    design_project = projects.get_project(db, user_id=user_id, project_id=design.project_id)
    scan_project = projects.get_project(db, user_id=user_id, project_id=scan.project_id)
    if design_project.workspace_id != scan_project.workspace_id:
        raise ValidationFailedError("design and scan must belong to the same workspace")
    require_workspace_role(db, user_id, design_project.workspace_id, WorkspaceRole.editor)
    session = db.scalar(
        sa.select(ScanSession).where(
            ScanSession.result_version_id == scan.id,
            ScanSession.status == ScanStatus.accepted,
        )
    )
    if session is None:
        raise ValidationFailedError("comparison requires an accepted scan result")
    metric_source = (session.capabilities or {}).get("metric_scale")
    trusted_metric = (
        session.mode in {ScanMode.rgb_depth, ScanMode.scanner}
        or metric_source in {"depth", "ar_pose", "scanner"}
        or (session.scale_hint_mm is not None and float(session.scale_confidence or 0) >= 0.5)
    )
    if not trusted_metric:
        raise ValidationFailedError(
            "comparison requires a metric scan",
            {"mode": session.mode.value, "metric_scale": metric_source or "unavailable"},
        )
    design_asset = model_asset_of(db, design)
    scan_asset = model_asset_of(db, scan)
    if (
        design_asset is None
        or scan_asset is None
        or design_asset.format not in REPAIRABLE_FORMATS
        or scan_asset.format not in REPAIRABLE_FORMATS
    ):
        raise ValidationFailedError(
            "both versions need comparable mesh assets",
            {"supported_formats": sorted(REPAIRABLE_FORMATS)},
        )
    return jobs.enqueue(
        db,
        workspace_id=design_project.workspace_id,
        job_type=PHYSICAL_COMPARE_JOB,
        input={
            "design_version_id": str(design.id),
            "design_asset_id": str(design_asset.id),
            "scan_version_id": str(scan.id),
            "scan_asset_id": str(scan_asset.id),
            "scan_session_id": str(session.id),
            "tolerance_mm": tolerance_mm,
            "samples": samples,
        },
        created_by=user_id,
        project_id=design.project_id,
        project_version_id=design.id,
        idempotency_key=idempotency_key,
        max_attempts=2,
    )
