"""Printing services: catalogue lookups, printer profile CRUD (T-070), analysis inputs
(T-071/T-072) and analyze/optimize job enqueueing (T-064/T-067)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.printing import (
    AnalysisKind,
    Material,
    PrintAnalysisRecord,
    PrinterModel,
    PrinterProfile,
)
from app.services import jobs, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

ANALYZE_JOB = "analyze_print"
OPTIMIZE_JOB = "optimize_print"
DEFAULT_MATERIAL_ID = "pla"


# --- catalogue ------------------------------------------------------------------------------


def list_printer_models(db: Session) -> list[PrinterModel]:
    return list(
        db.scalars(sa.select(PrinterModel).order_by(PrinterModel.vendor, PrinterModel.model))
    )


def list_materials(db: Session) -> list[Material]:
    return list(db.scalars(sa.select(Material).order_by(Material.kind, Material.name)))


def get_material(db: Session, material_id: str) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundError("material", material_id)
    return material


# --- printer profiles (T-070) --------------------------------------------------------------


def create_profile(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    printer_model_id: str,
    name: str,
    overrides: dict[str, Any],
) -> PrinterProfile:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if db.get(PrinterModel, printer_model_id) is None:
        raise NotFoundError("printer_model", printer_model_id)
    material_id = overrides.get("default_material_id")
    if material_id is not None:
        get_material(db, material_id)
    profile = PrinterProfile(
        workspace_id=workspace_id,
        user_id=user_id,
        printer_model_id=printer_model_id,
        name=name,
        **overrides,
    )
    if profile.is_default:
        _clear_default(db, workspace_id)
    db.add(profile)
    db.flush()
    return profile


def get_profile(db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID) -> PrinterProfile:
    profile = db.get(PrinterProfile, profile_id)
    if profile is None:
        raise NotFoundError("printer_profile", profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.viewer)
    return profile


def list_profiles(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[PrinterProfile]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return list(
        db.scalars(
            sa.select(PrinterProfile)
            .where(PrinterProfile.workspace_id == workspace_id)
            .order_by(PrinterProfile.is_default.desc(), PrinterProfile.created_at)
        )
    )


def update_profile(
    db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID, changes: dict[str, Any]
) -> PrinterProfile:
    profile = get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    if "printer_model_id" in changes and db.get(PrinterModel, changes["printer_model_id"]) is None:
        raise NotFoundError("printer_model", changes["printer_model_id"])
    if changes.get("default_material_id") is not None:
        get_material(db, changes["default_material_id"])
    if changes.get("is_default"):
        _clear_default(db, profile.workspace_id)
    for key, value in changes.items():
        setattr(profile, key, value)
    db.flush()
    return profile


def delete_profile(db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID) -> None:
    profile = get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    db.delete(profile)
    db.flush()


def _clear_default(db: Session, workspace_id: uuid.UUID) -> None:
    db.execute(
        sa.update(PrinterProfile)
        .where(PrinterProfile.workspace_id == workspace_id, PrinterProfile.is_default.is_(True))
        .values(is_default=False)
    )


# --- analysis inputs (T-071 / T-072) ----------------------------------------------------------


def _num(value: Decimal | None, fallback: float) -> float:
    return float(value) if value is not None else fallback


def printer_settings(db: Session, profile: PrinterProfile | None) -> dict[str, Any]:
    """Flatten model defaults + profile overrides into the worker's PrinterProfile fields."""
    if profile is None:
        return {}
    model = db.get(PrinterModel, profile.printer_model_id)
    assert model is not None
    return {
        "name": f"{model.vendor} {model.model} — {profile.name}",
        "bed_x_mm": float(model.bed_x_mm),
        "bed_y_mm": float(model.bed_y_mm),
        "bed_z_mm": float(model.bed_z_mm),
        "nozzle_mm": _num(profile.nozzle_mm, float(model.nozzle_mm)),
        "layer_height_mm": float(profile.layer_height_mm),
        "max_overhang_deg": _num(profile.max_overhang_deg, float(model.max_overhang_deg)),
        "print_speed_mm_s": _num(profile.print_speed_mm_s, float(model.print_speed_mm_s)),
        "technology": model.technology.value,
    }


def material_settings(material: Material | None) -> dict[str, Any]:
    if material is None:
        return {}
    return {
        "name": material.name,
        "density_g_cm3": float(material.density_g_cm3),
        "price_per_kg": float(material.price_per_kg),
        "currency": material.currency,
        "shrinkage_pct": float(material.shrinkage_pct),
        "min_wall_mm": float(material.min_wall_mm) if material.min_wall_mm is not None else None,
    }


def resolve_inputs(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    printer_profile_id: uuid.UUID | None,
    material_id: str | None,
) -> tuple[PrinterProfile | None, Material | None]:
    """Explicit ids win; otherwise the workspace default profile and its default material."""
    profile: PrinterProfile | None = None
    if printer_profile_id is not None:
        profile = get_profile(db, user_id=user_id, profile_id=printer_profile_id)
        if profile.workspace_id != workspace_id:
            raise NotFoundError("printer_profile", printer_profile_id)
    else:
        profile = db.scalar(
            sa.select(PrinterProfile).where(
                PrinterProfile.workspace_id == workspace_id, PrinterProfile.is_default.is_(True)
            )
        )
    resolved_material_id = material_id or (profile.default_material_id if profile else None)
    material = get_material(db, resolved_material_id or DEFAULT_MATERIAL_ID)
    return profile, material


# --- analyze / optimize jobs (T-064 / T-067) ---------------------------------------------------


def enqueue_analysis(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    kind: AnalysisKind,
    printer_profile_id: uuid.UUID | None,
    material_id: str | None,
    apply: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in ("stl", "obj", "ply", "glb", "gltf", "3mf"):
        raise ValidationFailedError("version has no mesh asset to analyze")
    profile, material = resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=project.workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=material_id,
    )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=ANALYZE_JOB if kind is AnalysisKind.analysis else OPTIMIZE_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "printer_profile_id": str(profile.id) if profile else None,
            "material_id": material.id if material else None,
            "apply": apply,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


def enqueue_slice_preview(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    printer_profile_id: uuid.UUID | None,
    idempotency_key: str | None = None,
) -> Job:
    """Geometric layer sections only; this job never produces printer instructions."""
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in ("stl", "obj", "ply", "glb", "gltf", "3mf"):
        raise ValidationFailedError("version has no mesh asset to slice")
    profile, _ = resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=project.workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=None,
    )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type="slice_preview",
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "printer_profile_id": str(profile.id) if profile else None,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


def get_analysis(db: Session, *, user_id: uuid.UUID, analysis_id: uuid.UUID) -> PrintAnalysisRecord:
    record = db.get(PrintAnalysisRecord, analysis_id)
    if record is None:
        raise NotFoundError("print_analysis", analysis_id)
    require_workspace_role(db, user_id, record.workspace_id, WorkspaceRole.viewer)
    return record


def list_analyses(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID
) -> list[PrintAnalysisRecord]:
    projects.get_version(db, user_id=user_id, version_id=version_id)
    return list(
        db.scalars(
            sa.select(PrintAnalysisRecord)
            .where(PrintAnalysisRecord.project_version_id == version_id)
            .order_by(PrintAnalysisRecord.created_at.desc())
        )
    )
