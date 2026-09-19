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


# --- AI Material (T-138, F-009) ---------------------------------------------------------------


def enqueue_material_adaptation(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    material_id: str,
    printer_profile_id: uuid.UUID | None = None,
    language: str = "en",
    preview: bool = True,
) -> tuple[Job, dict[str, Any]]:
    """Adapt the version's plan to a material: a preview version plus what changed."""
    from app.engineering import material as adaptation
    from app.services import ai_commands, edits

    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    material = db.get(Material, material_id)
    if material is None:
        raise ValidationFailedError(
            f"unknown material {material_id!r}", {"hint": "GET /api/v1/materials"}
        )
    operations = ai_commands.current_operations(db, version.id)
    if not operations:
        raise ValidationFailedError(
            "this version has no parametric history to adapt",
            {"hint": "ask the engineer instead: POST /models/{id}/engineering"},
        )
    profile, current = printing.resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=project.workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=None,
    )
    nozzle = float(profile.nozzle_mm) if profile and profile.nozzle_mm else 0.4
    measured = calibration.undersize_for(profile)
    plan = adaptation.adapt(
        operations,
        material_id=material_id,
        from_material_id=current.id if current else None,
        undersize_from=measured,
        undersize_to=measured,
        nozzle_mm=nozzle,
        language="ru" if language == "ru" else "en",
    )
    report: dict[str, Any] = {
        "material_id": material_id,
        "from_material_id": current.id if current else None,
        "wall_mm": plan.wall_mm,
        "changes": plan.changes,
        "skipped": plan.skipped,
        "operations": plan.operations,
    }
    if not plan.operations:
        raise ValidationFailedError(
            "; ".join(plan.changes) or f"nothing to change for {material.name}", report
        )
    job = edits.enqueue_edit(
        db,
        user_id=user_id,
        version_id=version.id,
        operations=plan.operations,
        label=(f"Под {material.name}" if language == "ru" else f"Adapted for {material.name}"),
        preview=preview,
    )
    return job, report


def enqueue_lightening(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    material_id: str | None = None,
    printer_profile_id: uuid.UUID | None = None,
    load: str = "structural",
    opening: str = "bottom",
    wall_mm: float | None = None,
    language: str = "en",
    preview: bool = True,
) -> tuple[Job, dict[str, Any]]:
    """F-007: hollow the version's plan to a wall the material carries — a preview version
    plus the report with the mass before (the job result carries the mass after)."""
    from app.engineering import optimize
    from app.services import ai_commands, edits

    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    operations = ai_commands.current_operations(db, version.id)
    if not operations:
        raise ValidationFailedError(
            "this version has no parametric history to optimize",
            {"hint": "cut or repair an imported mesh instead; hollowing needs a plan"},
        )
    profile, current = printing.resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=project.workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=material_id,
    )
    nozzle = float(profile.nozzle_mm) if profile and profile.nozzle_mm else 0.4
    chosen = material_id or (current.id if current else None)
    plan = optimize.lighten(
        operations,
        material_id=chosen,
        load=load,  # type: ignore[arg-type]
        opening=opening,  # type: ignore[arg-type]
        wall_mm=wall_mm,
        nozzle_mm=nozzle,
        language="ru" if language == "ru" else "en",
    )
    bodies = (version.provenance or {}).get("bodies") or []
    volume_before = float(bodies[-1].get("volume_mm3") or 0.0) if bodies else 0.0
    report: dict[str, Any] = {
        "goal": "lighter",
        "material_id": chosen,
        "wall_mm": plan.wall_mm,
        "opening": opening,
        "density_g_cm3": plan.density_g_cm3,
        "volume_before_mm3": volume_before,
        "mass_before_g": optimize.mass_g(volume_before, plan.density_g_cm3),
        "changes": plan.changes,
        "skipped": plan.skipped,
        "operations": plan.operations,
    }
    if not plan.operations:
        raise ValidationFailedError(
            "; ".join([*plan.changes, *plan.skipped]) or "nothing to lighten", report
        )
    job = edits.enqueue_edit(
        db,
        user_id=user_id,
        version_id=version.id,
        operations=plan.operations,
        label="Облегчено" if language == "ru" else "Lightened",
        preview=preview,
    )
    return job, report
