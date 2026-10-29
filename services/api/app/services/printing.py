"""Printing services: catalogue lookups, printer profile CRUD (T-070), analysis inputs
(T-071/T-072) and analyze/optimize job enqueueing (T-064/T-067)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from math import isfinite
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import Workspace, WorkspaceRole
from app.models.execution import Job
from app.models.printing import (
    AnalysisKind,
    Material,
    PrintAnalysisRecord,
    PrinterModel,
    PrinterProfile,
    PrintQueueSnapshot,
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
    _validate_raft_density_materials(db, overrides.get("raft_density_profiles"))
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
    _validate_raft_density_materials(db, changes.get("raft_density_profiles"))
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


def _validate_raft_density_materials(db: Session, profiles: dict[str, Any] | None) -> None:
    """Reject the whole typed map if even one key is not a catalogue material."""
    for material_id in profiles or {}:
        get_material(db, material_id)


def raft_density_for(profile: PrinterProfile | None, material_id: str) -> tuple[float, float, bool]:
    """Resolve one immutable printer/material pair, retaining the legacy 40/100 fallback."""
    configured = (profile.raft_density_profiles or {}).get(material_id) if profile else None
    if not isinstance(configured, dict):
        return 40.0, 100.0, False
    base = configured.get("base_density_pct")
    interface = configured.get("interface_density_pct")
    if (
        isinstance(base, bool)
        or not isinstance(base, int | float)
        or not 10.0 <= float(base) <= 70.0
        or isinstance(interface, bool)
        or not isinstance(interface, int | float)
        or not 50.0 <= float(interface) <= 100.0
    ):
        return 40.0, 100.0, False
    return float(base), float(interface), True


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


def _require_queue_plan(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    plan: dict[str, Any],
) -> None:
    """Reject forged, cross-workspace or geometrically inconsistent queue snapshots."""
    if (
        str(plan.get("workspace_id")) != str(workspace_id)
        or plan.get("dispatch_ready") is not False
    ):
        raise ValidationFailedError("print queue plan is not a workspace-bound draft")
    material = get_material(db, str(plan.get("material_id")))
    if plan.get("currency") != material.currency:
        raise ValidationFailedError("print queue material currency does not match the catalogue")
    settings_snapshot = plan.get("settings")
    expected_setting_keys = {"infill_density_pct", "wall_count", "margin_mm", "gap_mm"}
    if not isinstance(settings_snapshot, dict) or set(settings_snapshot) != expected_setting_keys:
        raise ValidationFailedError("print queue settings are incomplete")
    infill_density_pct = float(settings_snapshot["infill_density_pct"])
    wall_count_raw = settings_snapshot["wall_count"]
    wall_count = int(wall_count_raw)
    margin_mm = float(settings_snapshot["margin_mm"])
    gap_mm = float(settings_snapshot["gap_mm"])
    if (
        not all(isfinite(value) for value in (infill_density_pct, margin_mm, gap_mm))
        or isinstance(wall_count_raw, bool)
        or float(wall_count_raw) != wall_count
        or not 0 <= infill_density_pct <= 100
        or not 1 <= wall_count <= 6
        or not 0 <= margin_mm <= 50
        or not 0 <= gap_mm <= 50
    ):
        raise ValidationFailedError("print queue settings are outside planner bounds")
    fill_fraction = 0.15 + 0.85 * infill_density_pct / 100.0
    wall_factor = 1.0 + max(0, wall_count - 2) * 0.08

    assignments = plan.get("assignments")
    if not isinstance(assignments, list) or not 1 <= len(assignments) <= 20:
        raise ValidationFailedError("print queue must contain bounded printer assignments")
    profile_ids: set[uuid.UUID] = set()
    placements_seen: set[tuple[uuid.UUID, int]] = set()
    plate_count = 0
    item_count = 0
    total_mass_g = 0.0
    assignment_minutes: list[float] = []
    for assignment in assignments:
        profile_id = uuid.UUID(str(assignment["printer_profile_id"]))
        if profile_id in profile_ids:
            raise ValidationFailedError("print queue printer assignments must be unique")
        profile_ids.add(profile_id)
        profile = get_profile(db, user_id=user_id, profile_id=profile_id)
        if profile.workspace_id != workspace_id:
            raise NotFoundError("printer_profile", profile_id)
        settings = printer_settings(db, profile)
        canonical_bed = [settings["bed_x_mm"], settings["bed_y_mm"], settings["bed_z_mm"]]
        bed = [float(value) for value in assignment["bed_mm"]]
        if assignment["printer_name"] != profile.name or any(
            abs(actual - expected) > 0.001
            for actual, expected in zip(bed, canonical_bed, strict=True)
        ):
            raise ValidationFailedError("print queue printer snapshot does not match its profile")
        plates = assignment["plates"]
        if not isinstance(plates, list) or not 1 <= len(plates) <= 100:
            raise ValidationFailedError("print queue assignment must contain bounded plates")
        plate_count += len(plates)
        machine_minutes = 0.0
        for plate_index, plate in enumerate(plates, start=1):
            if int(plate["number"]) != plate_index:
                raise ValidationFailedError("print queue plate order is inconsistent")
            placements = plate["placements"]
            if not isinstance(placements, list) or not 1 <= len(placements) <= 100:
                raise ValidationFailedError("print queue plate must contain bounded placements")
            plate_minutes = 0.0
            rectangles: list[tuple[float, float, float, float]] = []
            for placement in placements:
                version_id = uuid.UUID(str(placement["version_id"]))
                copy_number = int(placement["copy_number"])
                key = (version_id, copy_number)
                if key in placements_seen or not 1 <= copy_number <= 50:
                    raise ValidationFailedError("print queue placements must be unique")
                placements_seen.add(key)
                version = projects.get_version(db, user_id=user_id, version_id=version_id)
                project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
                if project.workspace_id != workspace_id:
                    raise NotFoundError("project_version", version_id)
                extents, volume = _version_manufacturing_facts(version)
                actual_extents = [float(value) for value in placement["extents_mm"]]
                if (
                    str(placement["project_id"]) != str(project.id)
                    or placement["project_name"] != project.name
                    or any(
                        abs(actual - expected) > 0.001
                        for actual, expected in zip(actual_extents, extents, strict=True)
                    )
                    or abs(float(placement["volume_mm3"]) - volume) > 0.001
                ):
                    raise ValidationFailedError("print queue placement does not match its version")
                rotation = int(placement["plate_rotation_deg"])
                width, depth = (
                    (actual_extents[0], actual_extents[1])
                    if rotation == 0
                    else (actual_extents[1], actual_extents[0])
                )
                x, y = (float(value) for value in placement["plate_offset_mm"])
                expected_minutes = (
                    volume
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
                actual_minutes = float(placement["estimated_minutes"])
                numbers = [*actual_extents, volume, x, y, actual_minutes]
                if (
                    rotation not in (0, 90)
                    or any(not isfinite(value) or value < 0 for value in numbers)
                    or x < margin_mm - 0.001
                    or y < margin_mm - 0.001
                    or x + width > bed[0] - margin_mm + 0.001
                    or y + depth > bed[1] - margin_mm + 0.001
                    or actual_extents[2] > bed[2] + 0.001
                    or abs(actual_minutes - round(expected_minutes, 1)) > 0.001
                ):
                    raise ValidationFailedError("print queue placement is outside its printer bed")
                rectangle = (x, y, x + width, y + depth)
                if any(
                    not (
                        rectangle[2] + gap_mm <= other[0] + 0.001
                        or other[2] + gap_mm <= rectangle[0] + 0.001
                        or rectangle[3] + gap_mm <= other[1] + 0.001
                        or other[3] + gap_mm <= rectangle[1] + 0.001
                    )
                    for other in rectangles
                ):
                    raise ValidationFailedError("print queue placements overlap")
                rectangles.append(rectangle)
                plate_minutes += expected_minutes
                total_mass_g += (
                    volume / 1000.0 * float(material.density_g_cm3) * fill_fraction * wall_factor
                )
                item_count += 1
            if abs(float(plate["estimated_minutes"]) - round(plate_minutes, 1)) > 0.001:
                raise ValidationFailedError("print queue plate time is inconsistent")
            machine_minutes += plate_minutes
        if abs(float(assignment["estimated_minutes"]) - round(machine_minutes, 1)) > 0.001:
            raise ValidationFailedError("print queue printer time is inconsistent")
        assignment_minutes.append(machine_minutes)
    if item_count != plan.get("item_count") or plate_count != plan.get("plate_count"):
        raise ValidationFailedError("print queue summary does not match its placements")
    expected_makespan = round(max(assignment_minutes, default=0.0), 1)
    expected_mass = round(total_mass_g, 1)
    expected_cost = round(total_mass_g / 1000.0 * float(material.price_per_kg), 2)
    if (
        abs(float(plan["estimated_makespan_minutes"]) - expected_makespan) > 0.001
        or abs(float(plan["estimated_material_g"]) - expected_mass) > 0.001
        or abs(float(plan["estimated_material_cost"]) - expected_cost) > 0.001
    ):
        raise ValidationFailedError("print queue totals are inconsistent")


def get_print_queue(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> PrintQueueSnapshot:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    snapshot = db.scalar(
        sa.select(PrintQueueSnapshot).where(PrintQueueSnapshot.workspace_id == workspace_id)
    )
    if snapshot is None:
        raise NotFoundError("print_queue", workspace_id)
    return snapshot


def save_print_queue(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    plan: dict[str, Any],
    base_revision: int,
) -> PrintQueueSnapshot:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    _require_queue_plan(db, user_id=user_id, workspace_id=workspace_id, plan=plan)
    db.execute(sa.select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    snapshot = db.scalar(
        sa.select(PrintQueueSnapshot)
        .where(PrintQueueSnapshot.workspace_id == workspace_id)
        .with_for_update()
    )
    current_revision = snapshot.revision if snapshot is not None else 0
    if current_revision != base_revision:
        raise ConflictError(
            "print queue changed on another device",
            {"base_revision": base_revision, "current_revision": current_revision},
        )
    if snapshot is None:
        snapshot = PrintQueueSnapshot(
            workspace_id=workspace_id,
            revision=1,
            plan=plan,
            updated_by=user_id,
        )
        db.add(snapshot)
    else:
        snapshot.revision += 1
        snapshot.plan = plan
        snapshot.updated_by = user_id
    db.flush()
    return snapshot


def delete_print_queue(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, base_revision: int
) -> None:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    db.execute(sa.select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    snapshot = db.scalar(
        sa.select(PrintQueueSnapshot)
        .where(PrintQueueSnapshot.workspace_id == workspace_id)
        .with_for_update()
    )
    if snapshot is None:
        raise NotFoundError("print_queue", workspace_id)
    if snapshot.revision != base_revision:
        raise ConflictError(
            "print queue changed on another device",
            {"base_revision": base_revision, "current_revision": snapshot.revision},
        )
    db.delete(snapshot)
    db.flush()


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
    process_modifiers: list[dict[str, Any]] | None = None,
    adhesion_mode: str = "auto",
    brim_width_mm: float = 5.0,
    mouse_ear_diameter_mm: float = 10.0,
    mouse_ear_points_mm: list[tuple[float, float, float]] | None = None,
    adhesion_speed_pct: float = 100.0,
    raft_margin_mm: float = 5.0,
    raft_base_layers: int = 1,
    raft_interface_layers: int = 1,
    raft_base_speed_pct: float = 100.0,
    raft_interface_speed_pct: float = 100.0,
    raft_air_gap_mm: float = 0.15,
    skirt: bool = True,
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
    effective_material_id = material.id if material else DEFAULT_MATERIAL_ID
    raft_base_density_pct, raft_interface_density_pct, raft_density_profiled = raft_density_for(
        profile, effective_material_id
    )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=SLICE_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "printer_profile_id": str(profile.id) if profile else None,
            "material_id": effective_material_id,
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
            "process_modifiers": process_modifiers or [],
            "adhesion_mode": adhesion_mode,
            "brim_width_mm": brim_width_mm,
            "mouse_ear_diameter_mm": mouse_ear_diameter_mm,
            "mouse_ear_points_mm": mouse_ear_points_mm or [],
            "adhesion_speed_pct": adhesion_speed_pct,
            "raft_margin_mm": raft_margin_mm,
            "raft_base_layers": raft_base_layers,
            "raft_interface_layers": raft_interface_layers,
            "raft_base_speed_pct": raft_base_speed_pct,
            "raft_interface_speed_pct": raft_interface_speed_pct,
            "raft_air_gap_mm": raft_air_gap_mm,
            "raft_base_density_pct": raft_base_density_pct,
            "raft_interface_density_pct": raft_interface_density_pct,
            "raft_density_profiled": raft_density_profiled,
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
