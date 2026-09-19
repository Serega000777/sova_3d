"""Engineering assistant requests (T-118, F-005): ask the engineer about a version."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.geometry.region import parse_region
from app.models.core import WorkspaceRole
from app.models.engineering import EngineeringReportRecord
from app.models.execution import Job
from app.models.printing import Material
from app.services import calibration, jobs, printing, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

ENGINEERING_JOB = "engineering_advice"
MESH_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})
MAX_QUESTION = 500


def enqueue_advice(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    question: str | None,
    purpose: str | None,
    material_id: str | None,
    region: dict[str, Any] | None,
    printer_profile_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.viewer)

    # F-029: the printer's calibration, explicit or the workspace default, travels with the job.
    profile, _ = printing.resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=project.workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=None,
    )
    undersize_mm = calibration.undersize_for(profile)

    asset = model_asset_of(db, version)
    if asset is None or asset.format not in MESH_FORMATS:
        raise ValidationFailedError("this version has no mesh to measure")
    if question is not None and len(question) > MAX_QUESTION:
        raise ValidationFailedError(f"the question is too long (> {MAX_QUESTION} characters)")
    if material_id is not None and db.get(Material, material_id) is None:
        raise ValidationFailedError(
            f"unknown material {material_id!r}", {"hint": "GET /api/v1/printing/materials"}
        )
    if region is not None:
        try:
            parse_region(region)  # the same shape the region editor and the painter use
        except ValueError as exc:
            raise ValidationFailedError("the region is not valid", {"error": str(exc)}) from exc

    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=ENGINEERING_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "question": question,
            "purpose": purpose,
            "material_id": material_id,
            "region": region,
            "printer_profile_id": str(profile.id) if profile else None,
            "hole_undersize_mm": undersize_mm,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


def list_reports(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID
) -> list[EngineeringReportRecord]:
    projects.get_version(db, user_id=user_id, version_id=version_id)
    return list(
        db.scalars(
            sa.select(EngineeringReportRecord)
            .where(EngineeringReportRecord.project_version_id == version_id)
            .order_by(EngineeringReportRecord.created_at.desc())
        )
    )
