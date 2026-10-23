"""Bounded business starter (F-050) from measured print analyses.

It never invents demand or manufacturing cost. A product enters the plan only when its
immutable version has a stored print analysis with mass, time, material cost and currency.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.printing import Material, PrinterProfile
from app.models.versioning import AssetRole, ThumbnailAngle, VersionAsset
from app.services import printing, projects
from app.services.authz import require_workspace_role

MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _metric(metrics: dict[str, Any], key: str, version_id: uuid.UUID) -> Decimal:
    raw = metrics.get(key)
    if isinstance(raw, bool) or raw is None:
        raise ValidationFailedError(
            "print analysis has incomplete business metrics",
            {"version_id": str(version_id), "metric": key},
        )
    try:
        value = Decimal(str(raw))
    except Exception as exc:
        raise ValidationFailedError(
            "print analysis has invalid business metrics",
            {"version_id": str(version_id), "metric": key},
        ) from exc
    if not value.is_finite() or value < 0:
        raise ValidationFailedError(
            "print analysis has invalid business metrics",
            {"version_id": str(version_id), "metric": key},
        )
    return value


def create_plan(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    version_ids: list[uuid.UUID],
    target_margin_pct: Decimal,
    machine_rate_per_hour: Decimal,
    labour_per_unit: Decimal,
    packaging_per_unit: Decimal,
) -> dict[str, Any]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    if len(version_ids) != len(set(version_ids)):
        raise ValidationFailedError("business product versions must be unique")
    analyses = printing.latest_analyses_for(db, version_ids)
    missing = [str(version_id) for version_id in version_ids if version_id not in analyses]
    if missing:
        raise ValidationFailedError(
            "every business product needs a completed print analysis",
            {"version_ids": missing},
        )

    margin_fraction = target_margin_pct / Decimal(100)
    cards: list[dict[str, Any]] = []
    currencies: set[str] = set()
    for version_id in version_ids:
        version = projects.get_version(db, user_id=user_id, version_id=version_id)
        project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
        if project.workspace_id != workspace_id:
            raise ValidationFailedError("all business products must belong to the workspace")
        analysis = analyses[version_id]
        metrics = analysis.report.get("metrics")
        if not isinstance(metrics, dict):
            raise ValidationFailedError(
                "print analysis has incomplete business metrics",
                {"version_id": str(version_id), "metric": "metrics"},
            )
        material_cost = _metric(metrics, "total_cost", version_id)
        print_time_min = _metric(metrics, "print_time_min", version_id)
        mass_g = _metric(metrics, "mass_g", version_id)
        currency = metrics.get("currency")
        if not isinstance(currency, str) or len(currency) != 3:
            raise ValidationFailedError(
                "print analysis has invalid business metrics",
                {"version_id": str(version_id), "metric": "currency"},
            )
        currencies.add(currency.upper())
        unit_cost = _money(
            material_cost
            + machine_rate_per_hour * print_time_min / Decimal(60)
            + labour_per_unit
            + packaging_per_unit
        )
        recommended_price = _money(unit_cost / (Decimal(1) - margin_fraction))
        render_asset_id = db.scalar(
            sa.select(VersionAsset.asset_id)
            .where(
                VersionAsset.version_id == version_id,
                VersionAsset.role == AssetRole.thumbnail,
                sa.or_(
                    VersionAsset.thumbnail_angle == ThumbnailAngle.iso.value,
                    VersionAsset.thumbnail_angle.is_(None),
                ),
            )
            .limit(1)
        )
        material = db.get(Material, analysis.material_id) if analysis.material_id else None
        printer_profile = (
            db.get(PrinterProfile, analysis.printer_profile_id)
            if analysis.printer_profile_id
            else None
        )
        instructions = [
            {
                "ru": (
                    f"Производите неизменяемую версию v{version.sequence_no}; "
                    "не подменяйте её другой версией."
                ),
                "en": (
                    f"Manufacture immutable version v{version.sequence_no}; "
                    "do not substitute another version."
                ),
            },
            *(
                [
                    {
                        "ru": f"Материал: {material.name} ({material.id}).",
                        "en": f"Material: {material.name} ({material.id}).",
                    }
                ]
                if material is not None
                else []
            ),
            *(
                [
                    {
                        "ru": f"Профиль принтера: {printer_profile.name}.",
                        "en": f"Printer profile: {printer_profile.name}.",
                    }
                ]
                if printer_profile is not None
                else []
            ),
            {
                "ru": (
                    f"Ожидаемый результат по сохранённому анализу: {float(mass_g):g} г, "
                    f"{float(print_time_min):g} мин."
                ),
                "en": (
                    f"Expected output: {float(mass_g):g} g and "
                    f"{float(print_time_min):g} min from the stored analysis."
                ),
            },
            {
                "ru": (
                    f"Проверка печати: {analysis.status}, оценка {analysis.score}; "
                    "осмотрите физическое изделие перед выдачей."
                ),
                "en": (
                    f"Printability gate: {analysis.status}, score {analysis.score}; "
                    "inspect the physical output before fulfilment."
                ),
            },
        ]
        cards.append(
            {
                "project_id": project.id,
                "version_id": version.id,
                "title": project.name,
                "description": f"{project.name} · immutable version v{version.sequence_no}",
                "mass_g": float(mass_g),
                "print_time_min": float(print_time_min),
                "material_cost": material_cost,
                "unit_cost": unit_cost,
                "recommended_price": recommended_price,
                "gross_profit_per_unit": _money(recommended_price - unit_cost),
                "currency": currency.upper(),
                "render_ready": render_asset_id is not None,
                "render_asset_id": render_asset_id,
                "analysis_id": analysis.id,
                "analysis_status": analysis.status,
                "printability_score": analysis.score,
                "material_id": analysis.material_id,
                "printer_profile_id": analysis.printer_profile_id,
                "production_instructions": instructions,
            }
        )
    if len(currencies) != 1:
        raise ValidationFailedError(
            "product analyses use different currencies",
            {"currencies": sorted(currencies)},
        )
    return {
        "workspace_id": workspace_id,
        "target_margin_pct": target_margin_pct,
        "products": cards,
        "currency": next(iter(currencies)),
        "demand_claimed": False,
        "notes": [
            "Costs come from stored print analyses and the overhead entered for this plan.",
            "Recommended price is a margin calculation, not a demand or sales forecast.",
            "Generate an ISO thumbnail before publishing any card marked render_ready=false.",
        ],
    }
