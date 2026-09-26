"""Closed-loop printing (F-056): a print's outcome teaches the next print on that printer.

After a print the user says how it went — the symptoms a person can see (strings between
parts, corners lifting, a squashed first layer...). Each symptom has known causes and a
known, bounded correction; the corrections become this printer's tuning *for that
material* (PLA and PETG string for different reasons), and the slicer prints the next job
with them. Learning is incremental: every report moves a setting one step from where it is,
and a report that pushes a setting back the way it just came moves it half as far, so two
contradicting reports settle instead of oscillating. Symptoms with mechanical causes (a
layer shift, a clog) change nothing and say what to check instead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.errors import APIError, NotFoundError
from app.config import Settings
from app.models.core import Workspace, WorkspaceRole
from app.models.execution import Job
from app.models.printing import PrinterProfile
from app.services import ai_commands, jobs, printing
from app.services.authz import require_workspace_role

DIAGNOSE_PHOTO_JOB = "diagnose_print_photo"
MAX_REPORT_PHOTOS = 3

Symptom = Literal[
    "stringing",
    "warping",
    "poor_adhesion",
    "elephant_foot",
    "under_extrusion",
    "over_extrusion",
    "poor_overhangs",
    "layer_shift",
    "dimensions_off",
    "clogging",
]
Outcome = Literal["success", "partial", "failed"]
MAX_HISTORY = 30

# The worker's PrintTuning: defaults and the bounds it enforces (kept in step by a test).
DEFAULTS: dict[str, float] = {
    "nozzle_offset_c": 0.0,
    "bed_offset_c": 0.0,
    "retraction_mm": 1.2,
    "flow_pct": 100.0,
    "brim_mm": 0.0,
    "elephant_foot_mm": 0.0,
    "first_layer_speed_pct": 100.0,
}
# Tighter than the worker's hard limits: the most a run of reports may move a setting.
LIMITS: dict[str, tuple[float, float]] = {
    "nozzle_offset_c": (-15.0, 15.0),
    "bed_offset_c": (-10.0, 15.0),
    "retraction_mm": (0.4, 6.0),
    "flow_pct": (88.0, 115.0),
    "brim_mm": (0.0, 10.0),
    "elephant_foot_mm": (0.0, 0.4),
    "first_layer_speed_pct": (30.0, 100.0),
}


@dataclass(frozen=True, slots=True)
class Rule:
    causes: tuple[str, ...]
    steps: dict[str, float]  # setting -> change per report
    advice: str


RULES: dict[str, Rule] = {
    "stringing": Rule(
        ("oozing during travel", "nozzle too hot for this filament"),
        {"retraction_mm": 0.5, "nozzle_offset_c": -5.0},
        "Also dry the filament if it pops or hisses while printing.",
    ),
    "warping": Rule(
        ("corners cool and contract faster than the bed holds them",),
        {"brim_mm": 4.0, "bed_offset_c": 5.0},
        "Avoid drafts; ABS/ASA want an enclosure.",
    ),
    "poor_adhesion": Rule(
        ("first layer too fast or too cold to grip the bed",),
        {"first_layer_speed_pct": -20.0, "bed_offset_c": 5.0},
        "Clean the bed (isopropyl alcohol) and re-level or re-run Z offset.",
    ),
    "elephant_foot": Rule(
        ("the first layer is squashed wider than the rest",),
        {"elephant_foot_mm": 0.1},
        "If it persists, raise the Z offset slightly.",
    ),
    "under_extrusion": Rule(
        ("not enough plastic reaches the nozzle", "nozzle slightly too cold"),
        {"flow_pct": 4.0, "nozzle_offset_c": 5.0},
        "Check for a partial clog and that the spool unwinds freely.",
    ),
    "over_extrusion": Rule(
        ("more plastic than the lines need",),
        {"flow_pct": -4.0},
        "Measure the filament diameter; 1.75 mm is assumed.",
    ),
    "poor_overhangs": Rule(
        ("molten plastic sagging where nothing is underneath",),
        {"nozzle_offset_c": -5.0},
        "Turn supports on, or use Best orientation to put overhangs down.",
    ),
    "layer_shift": Rule(
        ("a mechanical skip: loose belt or pulley, or the head hitting the print",),
        {},
        "Tighten belts and pulley grub screws; lower print speed in the profile.",
    ),
    "dimensions_off": Rule(
        ("holes and outsides print a little off, per printer",),
        {},
        "Print the calibration coupon and enter the caliper readings: sizes are corrected "
        "from measurements, not guessed from a report.",
    ),
    "clogging": Rule(
        ("heat creeping up the nozzle, or debris in it",),
        {},
        "Do a cold pull or replace the nozzle; check the hotend fan runs.",
    ),
}


class PrintReport(BaseModel):
    material_id: str = Field(default="pla", pattern=r"^[a-z0-9_-]{1,32}$")
    outcome: Outcome
    symptoms: list[Symptom] = Field(default_factory=list, max_length=len(RULES))
    notes: str | None = Field(default=None, max_length=500)
    apply: bool = True

    @field_validator("symptoms")
    @classmethod
    def _unique(cls, symptoms: list[str]) -> list[str]:
        return list(dict.fromkeys(symptoms))


class PhotoReport(PrintReport):
    """A report with photos of the print: a vision model adds the symptoms it can see."""

    photo_asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_REPORT_PHOTOS)


class PhotoDiagnosisNotEnabledError(APIError):
    status_code = 501
    code = "photo_diagnosis_not_enabled"


class Change(BaseModel):
    setting: str
    before: float
    after: float


class Finding(BaseModel):
    symptom: Symptom
    causes: list[str]
    changes: list[Change]
    advice: str


class Diagnosis(BaseModel):
    material_id: str
    outcome: Outcome
    findings: list[Finding]
    tuning: dict[str, float]  # the whole tuning for this material after the report
    applied: bool
    reports: int


def tuning_of(profile: PrinterProfile | None, material_id: str) -> dict[str, float]:
    """The learned tuning for one material, complete and within bounds (defaults if none)."""
    stored = ((profile.calibration or {}).get("tuning") or {}).get(material_id) if profile else None
    tuning = dict(DEFAULTS)
    for name, value in (stored or {}).items():
        if name in LIMITS and isinstance(value, int | float) and not isinstance(value, bool):
            low, high = LIMITS[name]
            tuning[name] = min(max(float(value), low), high)
    return tuning


def _last_move(history: list[dict[str, Any]], material_id: str, setting: str) -> float:
    """The direction the most recent report moved this setting (0 if none did)."""
    for report in reversed(history):
        if report.get("material_id") != material_id:
            continue
        for change in report.get("changes", []):
            if change.get("setting") == setting:
                return float(change["after"]) - float(change["before"])
    return 0.0


def diagnose(
    report: PrintReport, current: dict[str, float], history: list[dict[str, Any]]
) -> tuple[list[Finding], dict[str, float]]:
    tuning = dict(current)
    findings: list[Finding] = []
    for symptom in report.symptoms:
        rule = RULES[symptom]
        changes: list[Change] = []
        for setting, step in rule.steps.items():
            if setting == "brim_mm" and tuning[setting] == 0:
                step = max(step, 5.0)  # a first brim is worth having at all
            if _last_move(history, report.material_id, setting) * step < 0:
                step /= 2  # the last report pushed the other way: settle, do not swing
            low, high = LIMITS[setting]
            before = tuning[setting]
            after = round(min(max(before + step, low), high), 3)
            if after != before:
                tuning[setting] = after
                changes.append(Change(setting=setting, before=before, after=after))
        findings.append(
            Finding(symptom=symptom, causes=list(rule.causes), changes=changes, advice=rule.advice)
        )
    return findings, tuning


def record_report(
    db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID, report: PrintReport
) -> Diagnosis:
    profile = printing.get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    return apply_report(db, profile, report)


def apply_report(
    db: Session,
    profile: PrinterProfile,
    report: PrintReport,
    seen_in_photos: list[str] | None = None,
) -> Diagnosis:
    """The report becomes history and (when `apply`) tuning. Authorization is the caller's."""
    calibration = dict(profile.calibration or {})
    history: list[dict[str, Any]] = list(calibration.get("print_reports") or [])
    current = tuning_of(profile, report.material_id)
    findings, proposed = diagnose(report, current, history)
    changed = [c.model_dump() for f in findings for c in f.changes] if report.apply else []
    history.append(
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "material_id": report.material_id,
            "outcome": report.outcome,
            "symptoms": list(report.symptoms),
            "seen_in_photos": seen_in_photos or [],
            "notes": report.notes,
            "changes": changed,
        }
    )
    calibration["print_reports"] = history[-MAX_HISTORY:]
    if report.apply:
        tunings = dict(calibration.get("tuning") or {})
        tunings[report.material_id] = {k: v for k, v in proposed.items() if v != DEFAULTS[k]}
        calibration["tuning"] = tunings
    profile.calibration = calibration
    db.flush()
    return Diagnosis(
        material_id=report.material_id,
        outcome=report.outcome,
        findings=findings,
        tuning=proposed if report.apply else current,
        applied=report.apply,
        reports=len(calibration["print_reports"]),
    )


def start_photo_diagnosis(
    db: Session,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    profile_id: uuid.UUID,
    report: PhotoReport,
) -> Job:
    profile = printing.get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    if settings.ai_provider != "anthropic":
        raise PhotoDiagnosisNotEnabledError(
            "reading print defects from photos needs a vision model (AI_PROVIDER=anthropic); "
            "name the symptoms instead",
            {"setting": "AI_PROVIDER"},
        )
    workspace = db.get(Workspace, profile.workspace_id)
    if workspace is None:
        raise NotFoundError("workspace", profile.workspace_id)
    ai_commands.enforce_quota(db, workspace, settings)
    photos = ai_commands.photos_for(
        db, workspace_id=profile.workspace_id, asset_ids=report.photo_asset_ids
    )
    return jobs.enqueue(
        db,
        workspace_id=profile.workspace_id,
        job_type=DIAGNOSE_PHOTO_JOB,
        input={
            "printer_profile_id": str(profile.id),
            "report": report.model_dump(mode="json", exclude={"photo_asset_ids"}),
            "photos": photos,
        },
        created_by=user_id,
    )


def reset_tuning(
    db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID, material_id: str
) -> PrinterProfile:
    profile = printing.get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    calibration = dict(profile.calibration or {})
    tunings = dict(calibration.get("tuning") or {})
    tunings.pop(material_id, None)
    calibration["tuning"] = tunings
    profile.calibration = calibration
    db.flush()
    return profile
