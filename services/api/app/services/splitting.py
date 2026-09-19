"""Cut a model into printable parts (F-081, T-142).

The API side records what to cut with and enqueues; the worker does the cutting. Two ways
in: the explicit request (planes, N parts, or "fit my printer"), and the sentence — "разрежь
на 3 части", "cut it in half", "split it so it fits my printer" — which the AI command
endpoint routes here without a planner, like a rollback.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import assets, jobs, printing, projects
from app.services.authz import require_workspace_role

SPLIT_JOB = "split_model"
Axis = Literal["x", "y", "z"]

# --- the sentence -----------------------------------------------------------------------------

_CUES = re.compile(
    r"\b(разреж\w*|разрез\w*|раздел\w*|распил\w*|порежь|нареж\w*|поруб\w*|"
    r"cut|split|divide|slice)\b",
    re.IGNORECASE,
)
_PARTS = re.compile(
    r"(?:на|into|in|to)\s+(\d+|дв[еа]|три|четыре|пять|шесть|two|three|four|five|six)\s*"
    r"(?:равн\w+\s+)?(?:част\w*|кус\w*|половин\w*|parts?|pieces?|halves|segments?)",
    re.IGNORECASE,
)
_HALF = re.compile(r"\b(пополам|напополам|in half|into halves)\b", re.IGNORECASE)
_FIT = re.compile(
    r"(влез\w*|помест\w*|уместил\w*|под (?:мой |свой )?принтер|на стол|в стол|"
    r"fits?\b.*\b(?:printer|bed)|for (?:my |the )?(?:printer|bed))",
    re.IGNORECASE,
)
_NO_DOWELS = re.compile(r"(без (?:штифт\w*|шкант\w*|соединит\w*)|no (?:dowels?|pins?))", re.I)
_AXIS_WORDS: tuple[tuple[re.Pattern[str], Axis], ...] = (
    (re.compile(r"(по высоте|по вертикали|горизонтальн\w*|по z|along z|horizontally)", re.I), "z"),
    (re.compile(r"(по ширине|по x|along x|по длине|lengthwise)", re.I), "x"),
    (re.compile(r"(по глубине|по y|along y)", re.I), "y"),
)
_NUMBER_WORDS = {
    "две": 2,
    "два": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}


@dataclass(frozen=True, slots=True)
class SplitIntent:
    parts: int | None = None
    axis: Axis | None = None
    fit_bed: bool = False
    dowels: bool = True

    def request(self, bed: dict[str, float] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"connectors": {"kind": "dowel" if self.dowels else "none"}}
        if self.parts is not None:
            body["parts"] = self.parts
        if self.axis is not None:
            body["axis"] = self.axis
        if self.fit_bed and bed is not None:
            body["bed"] = bed
        return body


def parse(prompt: str) -> SplitIntent | None:
    """What cutting a sentence asks for, or None when it is not about cutting at all."""
    if not _CUES.search(prompt):
        return None
    lowered = prompt.lower()
    parts: int | None = None
    if _HALF.search(lowered):
        parts = 2
    found = _PARTS.search(lowered)
    if found:
        word = found.group(1).lower()
        parts = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
    fit = bool(_FIT.search(lowered))
    if parts is None and not fit:
        return None  # "cut a slot here" is an edit for the planner, not a split
    axis = next((axis for pattern, axis in _AXIS_WORDS if pattern.search(lowered)), None)
    return SplitIntent(parts=parts, axis=axis, fit_bed=fit, dowels=not _NO_DOWELS.search(lowered))


# --- the request --------------------------------------------------------------------------------


def bed_of(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    printer_profile_id: uuid.UUID | None,
) -> dict[str, float] | None:
    """The bed the parts must fit: the named profile's, else the workspace default's."""
    profile, _ = printing.resolve_inputs(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        printer_profile_id=printer_profile_id,
        material_id=None,
    )
    settings = printing.printer_settings(db, profile)
    if not settings:
        return None
    return {
        "x_mm": settings["bed_x_mm"],
        "y_mm": settings["bed_y_mm"],
        "z_mm": settings["bed_z_mm"],
    }


def enqueue_split(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    request: dict[str, Any],
    fit_bed: bool = False,
    printer_profile_id: uuid.UUID | None = None,
    label: str | None = None,
    preview: bool = False,
    ai_request_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if assets.model_asset_of(db, version) is None:
        raise ValidationFailedError(
            "this version has no model to cut", {"version_id": str(version_id)}
        )

    body = dict(request)
    if fit_bed:
        bed = bed_of(
            db,
            user_id=user_id,
            workspace_id=project.workspace_id,
            printer_profile_id=printer_profile_id,
        )
        if bed is None:
            raise ValidationFailedError(
                "no printer profile to fit: add one on the Printers page", {"fit_bed": True}
            )
        body["bed"] = bed
    if not (body.get("planes") or body.get("parts") or body.get("bed")):
        raise ValidationFailedError(
            "say how to cut: planes, a number of parts, or fit the printer", {"request": body}
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=SPLIT_JOB,
        input={
            "version_id": str(version.id),
            "project_id": str(project.id),
            "request": body,
            "label": label,
            "preview": preview,
            "ai_request_id": str(ai_request_id) if ai_request_id else None,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
