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
SLICE_JOB = "slice"
DEFAULT_MATERIAL_ID = "pla"


def latest_analyses_for(
    db: Session, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PrintAnalysisRecord]:
    """Newest genuine analysis verdict per version, in one batched query."""
    if not version_ids:
        return {}
    ranked = (
        sa.select(
            PrintAnalysisRecord.id.label("analysis_id"),
            PrintAnalysisRecord.project_version_id.label("version_id"),
            sa.func.row_number()
            .over(
                partition_by=PrintAnalysisRecord.project_version_id,
                order_by=(PrintAnalysisRecord.created_at.desc(), PrintAnalysisRecord.id.desc()),
            )
            .label("position"),
        )
        .where(
            PrintAnalysisRecord.project_version_id.in_(version_ids),
            PrintAnalysisRecord.kind == AnalysisKind.analysis,
        )
        .subquery()
    )
    records = db.scalars(
        sa.select(PrintAnalysisRecord)
        .join(ranked, ranked.c.analysis_id == PrintAnalysisRecord.id)
        .where(ranked.c.position == 1)
    ).all()
    return {record.project_version_id: record for record in records}


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
        **calibration_settings(profile.calibration),
    }


# The worker's PrinterProfile bounds; a stored value outside them is left out, not sent.
_CALIBRATION_BOUNDS = {
    "xy_compensation_mm": (-1.0, 1.0),
    "shrinkage_pct": (-5.0, 5.0),
    "flow_pct": (85.0, 115.0),
}


def nozzle_of(db: Session, profile: PrinterProfile) -> float:
    """The profile's nozzle, or its printer model's."""
    model = db.get(PrinterModel, profile.printer_model_id)
    fallback = float(model.nozzle_mm) if model is not None else 0.4
    return _num(profile.nozzle_mm, fallback)


def calibration_settings(calibration: dict[str, Any] | None) -> dict[str, float]:
    """The measured corrections (F-028/F-029) the slicer applies: line fatness per side,
    X/Y shrinkage and extrusion flow. Anything missing, non-numeric or implausible is simply
    not applied."""
    applied: dict[str, float] = {}
    for key, (low, high) in _CALIBRATION_BOUNDS.items():
        value = (calibration or {}).get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if low <= float(value) <= high:
            applied[key] = float(value)
    return applied


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


# --- print-farm batch planning (F-032) --------------------------------------------------------


def _version_manufacturing_facts(version: Any) -> tuple[list[float], float]:
    """Return trusted metric extents and volume recorded by the geometry kernel."""
    bodies = (version.provenance or {}).get("bodies") or []
    body = (
        bodies[-1] if isinstance(bodies, list) and bodies and isinstance(bodies[-1], dict) else {}
    )
    bbox = body.get("bbox_mm") or {}
    size = bbox.get("size") if isinstance(bbox, dict) else None
    if (
        not isinstance(size, list)
        or len(size) != 3
        or any(
            isinstance(value, bool) or not isinstance(value, int | float) or value <= 0
            for value in size
        )
    ):
        raise ValidationFailedError(
            "version has no trusted metric bounds for batch planning",
            {"version_id": str(version.id)},
        )
    volume = body.get("volume_mm3")
    if isinstance(volume, bool) or not isinstance(volume, int | float) or volume <= 0:
        raise ValidationFailedError(
            "version has no trusted metric volume for batch planning",
            {"version_id": str(version.id)},
        )
    return [float(value) for value in size], float(volume)


def _shelf_candidate(
    plate: dict[str, Any],
    *,
    width: float,
    depth: float,
    bed_x: float,
    bed_y: float,
    margin: float,
    gap: float,
) -> tuple[float, float, float] | None:
    """A deterministic conservative rectangle placement; returns x, y, next row height."""
    x = float(plate["cursor_x"])
    y = float(plate["cursor_y"])
    row_height = float(plate["row_height"])
    if x + width <= bed_x - margin and y + depth <= bed_y - margin:
        return x, y, max(row_height, depth)
    x = margin
    y += row_height + gap
    if x + width <= bed_x - margin and y + depth <= bed_y - margin:
        return x, y, depth
    return None


def plan_print_farm_batch(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    requested_items: list[dict[str, Any]],
    printer_profile_ids: list[uuid.UUID],
    material_id: str,
    infill_density_pct: float,
    wall_count: int,
    margin_mm: float,
    gap_mm: float,
) -> dict[str, Any]:
    """Plan a bounded multi-model batch on concrete workspace printers.

    The result is deliberately a plan, not a dispatch: conservative metric bounding rectangles
    are packed on virtual plates and scheduled by estimated printer time. No G-code or physical
    printer state is invented.
    """
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    material = get_material(db, material_id)
    profiles: list[PrinterProfile] = []
    for profile_id in printer_profile_ids:
        profile = get_profile(db, user_id=user_id, profile_id=profile_id)
        if profile.workspace_id != workspace_id:
            raise NotFoundError("printer_profile", profile_id)
        profiles.append(profile)
    if not profiles:
        raise ValidationFailedError("select at least one printer profile")

    expanded: list[dict[str, Any]] = []
    for requested in requested_items:
        version_id = uuid.UUID(str(requested["version_id"]))
        version = projects.get_version(db, user_id=user_id, version_id=version_id)
        project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
        if project.workspace_id != workspace_id:
            raise NotFoundError("project_version", version_id)
        extents, volume = _version_manufacturing_facts(version)
        for copy_index in range(int(requested["quantity"])):
            expanded.append(
                {
                    "version_id": str(version.id),
                    "project_id": str(project.id),
                    "project_name": project.name,
                    "copy_number": copy_index + 1,
                    "extents_mm": extents,
                    "volume_mm3": volume,
                }
            )

    # Large rectangles first makes the shelf packing stable and substantially less wasteful.
    expanded.sort(
        key=lambda item: (item["extents_mm"][0] * item["extents_mm"][1], item["volume_mm3"]),
        reverse=True,
    )
    density = float(material.density_g_cm3)
    price_per_kg = float(material.price_per_kg)
    fill_fraction = 0.15 + 0.85 * infill_density_pct / 100.0
    wall_factor = 1.0 + max(0, wall_count - 2) * 0.08
    machines: list[dict[str, Any]] = []
    for profile in profiles:
        settings = printer_settings(db, profile)
        machines.append(
            {
                "profile": profile,
                "settings": settings,
                "plates": [],
                "estimated_minutes": 0.0,
            }
        )

    total_mass_g = 0.0
    for item in expanded:
        best: tuple[tuple[float, int, float], dict[str, Any]] | None = None
        for machine in machines:
            settings = machine["settings"]
            bed_x, bed_y, bed_z = settings["bed_x_mm"], settings["bed_y_mm"], settings["bed_z_mm"]
            x_size, y_size, z_size = item["extents_mm"]
            if z_size > bed_z:
                continue
            item_minutes = (
                item["volume_mm3"]
                * fill_fraction
                * wall_factor
                / max(
                    settings["nozzle_mm"]
                    * settings["layer_height_mm"]
                    * settings["print_speed_mm_s"],
                    0.001,
                )
                / 60.0
            )
            for plate_index in range(len(machine["plates"]) + 1):
                existing = plate_index < len(machine["plates"])
                plate = (
                    machine["plates"][plate_index]
                    if existing
                    else {
                        "cursor_x": margin_mm,
                        "cursor_y": margin_mm,
                        "row_height": 0.0,
                        "placements": [],
                        "estimated_minutes": 0.0,
                    }
                )
                for rotation, width, depth in ((0, x_size, y_size), (90, y_size, x_size)):
                    candidate = _shelf_candidate(
                        plate,
                        width=width,
                        depth=depth,
                        bed_x=bed_x,
                        bed_y=bed_y,
                        margin=margin_mm,
                        gap=gap_mm,
                    )
                    if candidate is None:
                        continue
                    x, y, row_height = candidate
                    projected = machine["estimated_minutes"] + item_minutes
                    score = (projected, 0 if existing else 1, bed_x * bed_y - width * depth)
                    choice = {
                        "machine": machine,
                        "plate_index": plate_index,
                        "new_plate": not existing,
                        "x": x,
                        "y": y,
                        "row_height": row_height,
                        "width": width,
                        "depth": depth,
                        "rotation": rotation,
                        "item_minutes": item_minutes,
                    }
                    if best is None or score < best[0]:
                        best = (score, choice)
        if best is None:
            raise ValidationFailedError(
                "batch item does not fit any selected printer",
                {"version_id": item["version_id"], "extents_mm": item["extents_mm"]},
            )
        choice = best[1]
        machine = choice["machine"]
        if choice["new_plate"]:
            machine["plates"].append(
                {
                    "cursor_x": margin_mm,
                    "cursor_y": margin_mm,
                    "row_height": 0.0,
                    "placements": [],
                    "estimated_minutes": 0.0,
                }
            )
        plate = machine["plates"][choice["plate_index"]]
        plate["placements"].append(
            {
                **item,
                "plate_offset_mm": [round(choice["x"], 3), round(choice["y"], 3)],
                "plate_rotation_deg": choice["rotation"],
                "estimated_minutes": round(choice["item_minutes"], 1),
            }
        )
        plate["cursor_x"] = choice["x"] + choice["width"] + gap_mm
        plate["cursor_y"] = choice["y"]
        plate["row_height"] = choice["row_height"]
        plate["estimated_minutes"] += choice["item_minutes"]
        machine["estimated_minutes"] += choice["item_minutes"]
        total_mass_g += item["volume_mm3"] / 1000.0 * density * fill_fraction * wall_factor

    assignments: list[dict[str, Any]] = []
    for machine in machines:
        settings = machine["settings"]
        if not machine["plates"]:
            continue
        assignments.append(
            {
                "printer_profile_id": str(machine["profile"].id),
                "printer_name": machine["profile"].name,
                "bed_mm": [settings["bed_x_mm"], settings["bed_y_mm"], settings["bed_z_mm"]],
                "estimated_minutes": round(machine["estimated_minutes"], 1),
                "plates": [
                    {
                        "number": index + 1,
                        "estimated_minutes": round(plate["estimated_minutes"], 1),
                        "placements": plate["placements"],
                    }
                    for index, plate in enumerate(machine["plates"])
                ],
            }
        )
    return {
        "workspace_id": str(workspace_id),
        "material_id": material.id,
        "currency": material.currency,
        "settings": {
            "infill_density_pct": infill_density_pct,
            "wall_count": wall_count,
            "margin_mm": margin_mm,
            "gap_mm": gap_mm,
        },
        "item_count": len(expanded),
        "plate_count": sum(len(machine["plates"]) for machine in machines),
        "estimated_makespan_minutes": round(
            max((machine["estimated_minutes"] for machine in machines), default=0.0), 1
        ),
        "estimated_material_g": round(total_mass_g, 1),
        "estimated_material_cost": round(total_mass_g / 1000.0 * price_per_kg, 2),
        "assignments": assignments,
        "dispatch_ready": False,
    }


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


def enqueue_slice(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    printer_profile_id: uuid.UUID | None,
    material_id: str | None,
    infill_density_pct: float,
    infill_pattern: str = "lines",
    wall_count: int,
    top_solid_layers: int = 4,
    bottom_solid_layers: int = 4,
    adaptive_layer_height: bool = False,
    min_layer_height_mm: float | None = None,
    max_layer_height_mm: float | None = None,
    supports: bool,
    support_type: str = "grid",
    support_modifiers: list[dict[str, Any]] | None = None,
    skirt: bool,
    idempotency_key: str | None = None,
) -> Job:
    """Real perimeters, infill and G-code (F-054, second stage) for one printer profile."""
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in ("stl", "obj", "ply", "glb", "gltf", "3mf"):
        raise ValidationFailedError("version has no mesh asset to slice")
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
        job_type=SLICE_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "printer_profile_id": str(profile.id) if profile else None,
            "material_id": material.id if material else DEFAULT_MATERIAL_ID,
            "infill_density_pct": infill_density_pct,
            "infill_pattern": infill_pattern,
            "wall_count": wall_count,
            "top_solid_layers": top_solid_layers,
            "bottom_solid_layers": bottom_solid_layers,
            "adaptive_layer_height": adaptive_layer_height,
            "min_layer_height_mm": min_layer_height_mm,
            "max_layer_height_mm": max_layer_height_mm,
            "supports": supports,
            "support_type": support_type,
            "support_modifiers": support_modifiers or [],
            "skirt": skirt,
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
