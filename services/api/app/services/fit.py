"""AI Fit Test (T-130, F-027): put two parts together, get a verdict and the fix.

The worker measures how the two surfaces meet; this module turns that into an engineer's
sentence — "the peg is 0.2 mm too big for the hole: for a sliding fit make the hole 10.7 mm"
— and, when part A's plan has a round opening the other part goes into, into operations
the edit endpoint accepts as they are.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.engineering import knowledge as kb
from app.models.core import WorkspaceRole
from app.models.engineering import FitTestRecord
from app.models.execution import Job
from app.services import ai_commands, jobs, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

FIT_JOB = "fit_test"
MESH_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})

Language = Literal["ru", "en"]


class Placement(BaseModel):
    align: Literal["centre", "origin"] = "centre"
    offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate_z_deg: float = Field(default=0.0, ge=-360, le=360)


class Advice(BaseModel):
    """What the engineer says about the fit, and the fix when it is a number in A's plan."""

    summary: str
    recommendation: str | None = None
    fix: dict[str, Any] | None = None  # {"label", "operations"} for POST /models/{a}/edits
    numbers: dict[str, float] = Field(default_factory=dict)


def enqueue_fit_test(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_a_id: uuid.UUID,
    version_b_id: uuid.UUID,
    placement: Placement,
    wanted: kb.Fit = "sliding",
    material_id: str | None = None,
    language: Language = "en",
    auto_place: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    a = projects.get_version(db, user_id=user_id, version_id=version_a_id)
    b = projects.get_version(db, user_id=user_id, version_id=version_b_id)
    project = projects.get_project(db, user_id=user_id, project_id=a.project_id)
    other = projects.get_project(db, user_id=user_id, project_id=b.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.viewer)
    if other.workspace_id != project.workspace_id:
        raise ValidationFailedError("both parts must belong to the same workspace")
    asset_a = model_asset_of(db, a)
    asset_b = model_asset_of(db, b)
    for asset, name in ((asset_a, "A"), (asset_b, "B")):
        if asset is None or asset.format not in MESH_FORMATS:
            raise ValidationFailedError(f"part {name} has no mesh to fit")
    assert asset_a is not None and asset_b is not None
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=FIT_JOB,
        input={
            "version_a_id": str(a.id),
            "version_b_id": str(b.id),
            "asset_a_id": str(asset_a.id),
            "asset_b_id": str(asset_b.id),
            "placement": placement.model_dump(mode="json"),
            "wanted": wanted,
            "material_id": material_id,
            "language": language,
            "auto_place": auto_place,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=a.id,
        idempotency_key=idempotency_key,
    )


def list_fit_tests(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID
) -> list[FitTestRecord]:
    projects.get_version(db, user_id=user_id, version_id=version_id)
    return list(
        db.scalars(
            sa.select(FitTestRecord)
            .where(FitTestRecord.version_a_id == version_id)
            .order_by(FitTestRecord.created_at.desc())
        )
    )


# --- the engineer's sentence -----------------------------------------------------------------


def _mm(value: float) -> str:
    return f"{value:g} mm"


def _round_openings(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cut_tools = {
        op.get("tool") for op in operations if op.get("type") == "boolean" and op.get("op") == "cut"
    }
    return [
        op
        for op in operations
        if op.get("type") == "add_hole"
        or (op.get("type") == "create_cylinder" and op.get("id") in cut_tools)
    ]


def advise(
    result: dict[str, Any],
    *,
    operations_a: list[dict[str, Any]],
    b_bbox_mm: list[list[float]] | None,
    wanted: kb.Fit,
    material_id: str | None,
    language: Language,
) -> Advice:
    """From the measured fit to what to do about it."""
    ru = language == "ru"
    recommendation: str | None
    verdict = result.get("verdict")
    penetration = float(result.get("max_penetration_mm") or 0.0)
    clearance = result.get("min_clearance_mm")
    allowance = kb.fit_allowance_mm(wanted, material_id)  # on the diameter / the nominal
    fit_word = kb.FIT_WORDS_RU[wanted] if ru else f"{wanted} fit"
    for_fit = f"для {kb.FIT_WORDS_RU_GENITIVE[wanted]}" if ru else f"for a {fit_word}"
    numbers: dict[str, float] = {"allowance_mm": allowance, "max_penetration_mm": penetration}
    if clearance is not None:
        numbers["min_clearance_mm"] = float(clearance)

    # The size of what goes in, if it looks round (a peg, a pipe, a shaft).
    b_width: float | None = None
    if b_bbox_mm and len(b_bbox_mm) == 2:
        (x0, y0, _), (x1, y1, _) = b_bbox_mm
        w, d = x1 - x0, y1 - y0
        if w > 0 and d > 0 and abs(w - d) / max(w, d) < 0.1:
            b_width = round((w + d) / 2, 2)

    if verdict == "collides":
        grow = round(2 * penetration + allowance, 2)  # both sides plus the fit
        summary = (
            f"Не подходит: детали пересекаются на {_mm(penetration)} с каждой стороны"
            + (
                f", объём пересечения {result['interference_mm3']:g} мм³"
                if result.get("interference_mm3")
                else ""
            )
            + "."
            if ru
            else f"Does not fit: the parts overlap by {_mm(penetration)} per side"
            + (
                f", {result['interference_mm3']:g} mm³ of interference"
                if result.get("interference_mm3")
                else ""
            )
            + "."
        )
        fix = None
        openings = _round_openings(operations_a)
        target_d = None
        if b_width is not None:
            target_d = round(b_width + allowance, 2)
            candidates = [
                op
                for op in openings
                if abs(float(op.get("diameter_mm", 0)) - b_width) <= max(1.0, 0.2 * b_width)
            ]
            if candidates:
                fix = {
                    "label": ("Отверстие под " if ru else "Opening for ") + f"Ø{b_width:g}",
                    "operations": [
                        {
                            "type": "set_parameter",
                            "operation": str(op["id"]),
                            "parameter": "diameter_mm",
                            "value": target_d,
                        }
                        for op in candidates
                    ],
                }
        if target_d is not None:
            recommendation = (
                f"{for_fit.capitalize()} сделайте отверстие Ø{target_d:g} мм "
                f"(деталь Ø{b_width:g} + допуск {allowance:g} мм)."
                if ru
                else f"{for_fit.capitalize()} make the opening Ø{target_d:g} mm "
                f"(the part is Ø{b_width:g} + {allowance:g} mm allowance)."
            )
            numbers["target_diameter_mm"] = target_d
        else:
            recommendation = (
                f"Увеличьте посадочное место на {_mm(grow)} (на обе стороны плюс допуск {for_fit})."
                if ru
                else f"Enlarge the seat by {_mm(grow)} (both sides plus the {fit_word} allowance)."
            )
            numbers["grow_mm"] = grow
        return Advice(summary=summary, recommendation=recommendation, fix=fix, numbers=numbers)

    if verdict == "apart":
        summary = (
            "Детали не соприкасаются в этом положении — проверьте смещение."
            if ru
            else "The parts do not meet in this placement — check the offset."
        )
        return Advice(summary=summary, numbers=numbers)

    gap = float(clearance or 0.0)
    have = kb.FIT_WORDS_RU.get(verdict, verdict) if ru else f"{verdict} fit"  # type: ignore[arg-type]
    summary = (
        f"Собирается: зазор {_mm(gap)} на сторону — это {have}."
        if ru
        else f"It goes together: {_mm(gap)} of clearance per side — a {have}."
    )
    recommendation = None
    if verdict != wanted:
        want_side = round(allowance / 2, 3)
        delta = round((want_side - gap) * 2, 2)
        if abs(delta) >= 0.05:
            recommendation = (
                f"{for_fit.capitalize()} измените посадочное место на {delta:+g} мм по диаметру."
                if ru
                else f"{for_fit.capitalize()} change the seat by {delta:+g} mm on the diameter."
            )
            numbers["change_diameter_mm"] = delta
    return Advice(summary=summary, recommendation=recommendation, numbers=numbers)


def operations_of(db: Session, version_id: uuid.UUID) -> list[dict[str, Any]]:
    return ai_commands.current_operations(db, version_id)
