"""Camera problem -> measured functional part proposals (bounded F-020)."""

from __future__ import annotations

import math
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.modeling import DimensionedDrawingBody, DrawingHole
from app.models.references import ProjectReference
from app.services import projects

router = APIRouter(tags=["functional-parts"])


class FunctionalPartProposalBody(BaseModel):
    problem: str = Field(min_length=3, max_length=500)
    kind: Literal["mounting_plate"] = "mounting_plate"
    clearance_mm: float = Field(default=0.5, ge=0, le=10)
    thickness_mm: float = Field(default=4, ge=2, le=20)
    hole_diameter_mm: float = Field(default=4.7, ge=2, le=12)


class MeasuredEvidence(BaseModel):
    label: str
    value_mm: float


class FunctionalPartProposalOut(BaseModel):
    kind: Literal["mounting_plate"]
    title: str
    problem: str
    recognizes_contents: Literal[False] = False
    evidence: list[MeasuredEvidence]
    drawing: DimensionedDrawingBody
    assumptions: list[str]
    physical_validation_required: Literal[True] = True


def _distance(settings: dict[str, object], measurement: dict[str, object]) -> float | None:
    try:
        points = measurement["points"]
        if not isinstance(points, list) or len(points) != 2:
            return None
        a, b = points
        if not isinstance(a, list) or not isinstance(b, list) or len(a) != 2 or len(b) != 2:
            return None
        width_px = float(str(settings["width_px"]))
        height_px = float(str(settings["height_px"]))
        width_mm = float(str(settings["width_mm"]))
        if min(width_px, height_px, width_mm) <= 0:
            return None
        dx = (float(b[0]) - float(a[0])) * width_px
        dy = (float(b[1]) - float(a[1])) * height_px
    except (KeyError, TypeError, ValueError):
        return None
    value = math.hypot(dx, dy) * width_mm / width_px
    return value if math.isfinite(value) and value > 0 else None


def _label_axis(label: str) -> Literal["width", "height"] | None:
    lowered = label.casefold()
    if any(cue in lowered for cue in ("ширин", "width", "горизонт")):
        return "width"
    if any(cue in lowered for cue in ("высот", "height", "вертикал")):
        return "height"
    return None


@router.post(
    "/projects/{project_id}/functional-part-proposal",
    response_model=FunctionalPartProposalOut,
)
def propose_functional_part(
    project_id: uuid.UUID,
    body: FunctionalPartProposalBody,
    db: DbDep,
    principal: PrincipalDep,
) -> FunctionalPartProposalOut:
    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    problem = body.problem.casefold()
    if not any(
        cue in problem
        for cue in ("креп", "пластин", "держател", "mount", "plate", "bracket", "holder")
    ):
        raise ValidationFailedError(
            "the bounded camera workflow currently supports a mounting plate only",
            {"supported_kind": "mounting_plate"},
        )
    reference = db.get(ProjectReference, project_id)
    if reference is None:
        raise ValidationFailedError("a calibrated project reference is required")
    settings = dict(reference.settings or {})
    raw_measurements = settings.get("measurements")
    if not isinstance(raw_measurements, list):
        raw_measurements = []
    measured: dict[str, MeasuredEvidence] = {}
    for item in raw_measurements:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        axis = _label_axis(label)
        value = _distance(settings, item)
        if axis is not None and value is not None and axis not in measured:
            measured[axis] = MeasuredEvidence(label=label, value_mm=round(value, 3))
    if set(measured) != {"width", "height"}:
        raise ValidationFailedError(
            "two calibrated measurements labelled width and height are required",
            {"required_labels": ["width", "height"], "found": sorted(measured)},
        )

    width = measured["width"].value_mm - body.clearance_mm * 2
    height = measured["height"].value_mm - body.clearance_mm * 2
    if min(width, height) < 25:
        raise ValidationFailedError(
            "the measured area is too small for the bounded mounting plate",
            {"minimum_mm": 25, "width_mm": width, "height_mm": height},
        )
    inset = max(body.hole_diameter_mm, min(width, height) * 0.15)
    x = width / 2 - inset
    y = height / 2 - inset
    drawing = DimensionedDrawingBody(
        width_mm=round(width, 3),
        height_mm=round(height, 3),
        thickness_mm=body.thickness_mm,
        corner_radius_mm=round(min(5.0, min(width, height) * 0.1), 3),
        holes=[
            DrawingHole(
                x_mm=round(x_sign * x, 3),
                y_mm=round(y_sign * y, 3),
                diameter_mm=body.hole_diameter_mm,
            )
            for x_sign, y_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ],
    )
    return FunctionalPartProposalOut(
        kind="mounting_plate",
        title="Measured mounting plate",
        problem=body.problem,
        evidence=[measured["width"], measured["height"]],
        drawing=drawing,
        assumptions=[
            "The two labelled lines lie on the same flat plane as the required part.",
            "Photo contents are not recognized; only the saved calibration and points are used.",
            "Hole placement is a bounded four-corner layout, not detected fasteners.",
        ],
    )
