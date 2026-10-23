"""Specialized facade editing for exact rectangular house-box versions."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, status
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.orm import Session

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering.facade import (
    MAX_OPENINGS,
    FacadeOpening,
    FacadeRequest,
    SurfaceMaterial,
    opening_key,
    surface_keys,
    variant_estimate,
)
from app.engineering.house_box import HouseBoxRequest
from app.models.core import WorkspaceRole
from app.models.execution import Job, JobStatus
from app.models.printing import Material
from app.models.scanning import ScanSession
from app.models.versioning import ProjectVersion
from app.services import jobs, projects
from app.services.authz import require_workspace_role
from app.services.house_boxes import HOUSE_BOX_JOB

router = APIRouter(tags=["facades"])
FACADE_ADAPTER = TypeAdapter(FacadeRequest)
SURFACE_ADAPTER = TypeAdapter(SurfaceMaterial)


class FacadeOpeningBody(BaseModel):
    opening_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    kind: Literal["window", "door", "opening"]
    side: Literal["front", "back", "left", "right"]
    center_mm: float = Field(ge=100, le=49_900)
    width_mm: float = Field(ge=300, le=5_000)
    height_mm: float = Field(ge=300, le=5_000)
    sill_mm: float | None = Field(
        default=None,
        ge=0,
        le=15_000,
        description="Window sill height (default 900). Doors start at floor level: omit or 0.",
    )
    floor: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description=(
            "Optional 1-based floor address. When present, sill_mm is measured from that "
            "floor; when absent, sill_mm remains the legacy absolute facade height."
        ),
    )


class SurfaceMaterialBody(BaseModel):
    surface_key: str = Field(pattern=r"^[a-z0-9_.-]{1,160}$")
    colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    material_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    unit_price_per_m2: float | None = Field(default=None, ge=0, le=1_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    price_source_url: str | None = Field(default=None, max_length=500, pattern=r"^https://[^\s]+$")

    @model_validator(mode="after")
    def pricing_is_complete(self) -> SurfaceMaterialBody:
        values = (self.unit_price_per_m2, self.currency, self.price_source_url)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError(
                "facade price requires unit_price_per_m2, currency and price_source_url together"
            )
        return self


class FacadeEditBody(BaseModel):
    length_mm: float | None = Field(default=None, ge=2_000, le=50_000)
    width_mm: float | None = Field(default=None, ge=2_000, le=50_000)
    floor_height_mm: float | None = Field(default=None, ge=2_200, le=6_000)
    wall_thickness_mm: float = Field(default=250, ge=100, le=600)
    roof: Literal["none", "flat", "gable", "shed", "hip"] = "flat"
    roof_height_mm: float = Field(default=1_200, ge=200, le=5_000)
    overhang_mm: float = Field(default=300, ge=0, le=2_000)
    openings: list[FacadeOpeningBody] = Field(default_factory=list, max_length=MAX_OPENINGS)
    surface_assignments: list[SurfaceMaterialBody] | None = Field(default=None, max_length=512)
    variant_name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("variant_name")
    @classmethod
    def clean_variant_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("variant_name must not be blank")
        return cleaned


class ScannedFacadeBody(BaseModel):
    length_mm: float = Field(ge=2_000, le=50_000)
    width_mm: float = Field(ge=2_000, le=50_000)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    floors: int = Field(default=1, ge=1, le=3)
    wall_thickness_mm: float = Field(default=250, ge=100, le=600)
    roof: Literal["none", "flat", "gable", "shed", "hip"] = "flat"
    roof_height_mm: float = Field(default=1_200, ge=200, le=5_000)
    overhang_mm: float = Field(default=300, ge=0, le=2_000)
    openings: list[FacadeOpeningBody] = Field(default_factory=list, max_length=MAX_OPENINGS)
    wall_colour: str = Field(default="#c9ced8", pattern=r"^#[0-9a-fA-F]{6}$")


class FacadeVariantApplyBody(BaseModel):
    variant_version_id: uuid.UUID


class FacadeCommandProposalBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)


class FacadeCommandApplyBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    expected_current_mm: float = Field(ge=0, le=50_000)
    proposed_new_mm: float = Field(ge=0, le=50_000)


class FacadeCommandProposalOut(BaseModel):
    source_version_id: uuid.UUID
    parameter: Literal[
        "house_length",
        "house_width",
        "floor_height",
        "roof_overhang",
        "wall_thickness",
        "roof_height",
    ]
    label_ru: str
    label_en: str
    current_value_mm: float
    new_value_mm: float
    unit: Literal["mm"] = "mm"


class FacadeVariantOut(BaseModel):
    version_id: uuid.UUID
    sequence_no: int
    name: str
    created_at: datetime
    surface_keys: list[str]
    surface_assignments: list[SurfaceMaterialBody]
    category_areas_m2: dict[str, float]
    assigned_area_m2: float
    priced_area_m2: float
    unpriced_assigned_area_m2: float
    estimated_cost: float | None
    currency: str | None


FACADE_JOB = "edit_facade"

_VALUE = r"(?P<value>(?:\d+(?:[.,]\d+)?|[.,]\d+))"
_UNIT = r"(?P<unit>мм|mm|см|cm|м|m)"
_OVERHANG_PATTERNS = (
    re.compile(
        rf"^(?:установи|измени|сделай|поставь)\s+(?:свес(?:\s+крыши)?|вылет\s+крыши)\s+(?:на\s+|до\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:увеличь|уменьши)\s+(?:свес(?:\s+крыши)?|вылет\s+крыши)\s+до\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:set|change|make)\s+(?:the\s+)?(?:roof\s+)?overhang\s+(?:to\s+|at\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:increase|decrease)\s+(?:the\s+)?(?:roof\s+)?overhang\s+to\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>увеличь|уменьши)\s+(?:свес(?:\s+крыши)?|вылет\s+крыши)\s+на\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>increase|decrease)\s+(?:the\s+)?(?:roof\s+)?overhang\s+by\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
)
_WALL_THICKNESS_PATTERNS = (
    re.compile(
        rf"^(?:установи|измени|сделай|поставь)\s+толщину\s+(?:стены|стен)\s+(?:на\s+|до\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:увеличь|уменьши)\s+толщину\s+(?:стены|стен)\s+до\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:set|change|make)\s+(?:the\s+)?wall\s+thickness\s+(?:to\s+|at\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:increase|decrease)\s+(?:the\s+)?wall\s+thickness\s+to\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>увеличь|уменьши)\s+толщину\s+(?:стены|стен)\s+на\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>increase|decrease)\s+(?:the\s+)?wall\s+thickness\s+by\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
)
_ROOF_HEIGHT_PATTERNS = (
    re.compile(
        rf"^(?:установи|измени|сделай|поставь)\s+высоту\s+крыши\s+(?:на\s+|до\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:увеличь|уменьши)\s+высоту\s+крыши\s+до\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:set|change|make)\s+(?:the\s+)?roof\s+height\s+(?:to\s+|at\s+)?{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:increase|decrease)\s+(?:the\s+)?roof\s+height\s+to\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>увеличь|уменьши)\s+высоту\s+крыши\s+на\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<direction>increase|decrease)\s+(?:the\s+)?roof\s+height\s+by\s+{_VALUE}\s*{_UNIT}$",
        re.IGNORECASE,
    ),
)


def _dimension_patterns(ru_name: str, en_name: str) -> tuple[re.Pattern[str], ...]:
    return (
        re.compile(
            rf"^(?:установи|измени|сделай|поставь)\s+{ru_name}\s+(?:на\s+|до\s+)?{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?:увеличь|уменьши)\s+{ru_name}\s+до\s+{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?:set|change|make)\s+(?:the\s+)?{en_name}\s+(?:to\s+|at\s+)?{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?:increase|decrease)\s+(?:the\s+)?{en_name}\s+to\s+{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?P<direction>увеличь|уменьши)\s+{ru_name}\s+на\s+{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?P<direction>increase|decrease)\s+(?:the\s+)?{en_name}\s+by\s+{_VALUE}\s*{_UNIT}$",
            re.IGNORECASE,
        ),
    )


_HOUSE_LENGTH_PATTERNS = _dimension_patterns(
    r"длину\s+(?:дома|здания)", r"(?:house|building)\s+length"
)
_HOUSE_WIDTH_PATTERNS = _dimension_patterns(
    r"ширину\s+(?:дома|здания)", r"(?:house|building)\s+width"
)
_FLOOR_HEIGHT_PATTERNS = _dimension_patterns(
    r"высоту\s+(?:этажа|стен)", r"(?:floor|storey|story|wall)\s+height"
)

FacadeCommandParameter = Literal[
    "house_length",
    "house_width",
    "floor_height",
    "roof_overhang",
    "wall_thickness",
    "roof_height",
]


@dataclass(frozen=True)
class FacadeCommandChange:
    request: FacadeRequest
    parameter: FacadeCommandParameter
    label_ru: str
    label_en: str
    current_value_mm: float
    new_value_mm: float


class IneligibleVersionError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _producing_job(db: Session, version: ProjectVersion) -> Job | None:
    """The succeeded server job that wrote this version. Provenance is client-writable through
    the versions API, so only the job row (input validated and enqueued by the server) counts."""
    return db.scalar(
        sa.select(Job)
        .where(
            Job.project_id == version.project_id,
            Job.type.in_((HOUSE_BOX_JOB, FACADE_JOB)),
            Job.status == JobStatus.succeeded,
            Job.result["version_id"].astext == str(version.id),
        )
        .limit(1)
    )


def _scan_ancestor(db: Session, version: ProjectVersion) -> ScanSession | None:
    current: ProjectVersion | None = version
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        session = db.scalar(
            sa.select(ScanSession).where(ScanSession.result_version_id == current.id).limit(1)
        )
        if session is not None:
            return session
        current = (
            db.get(ProjectVersion, current.parent_version_id)
            if current.parent_version_id
            else None
        )
    return None


def _rectangular_house(db: Session, version: ProjectVersion) -> HouseBoxRequest:
    """Follow facade edits back to the house-box job and require its validated shape to be
    an exact rectangle; anything else (scans, imports, L/T shapes, forged provenance) fails."""
    seen: set[uuid.UUID] = set()
    current = version
    while current.id not in seen:
        seen.add(current.id)
        job = _producing_job(db, current)
        if job is None:
            raise IneligibleVersionError(
                "not_house_box",
                "the facade editor needs a rectangular house-box version; this version was "
                "not generated by the house-box builder (scanned, imported or hand-made "
                "geometry is not eligible)",
            )
        if job.type == HOUSE_BOX_JOB:
            try:
                house = HouseBoxRequest(**dict(job.input.get("request") or {}))
            except (TypeError, ValueError) as exc:
                raise IneligibleVersionError(
                    "invalid_house_box", f"the source house-box request is invalid: {exc}"
                ) from exc
            if house.shape != "rectangle":
                raise IneligibleVersionError(
                    "not_rectangular",
                    f"the facade editor needs a rectangular house-box version; "
                    f"this house is {house.shape}",
                )
            if house.stair is not None:
                raise IneligibleVersionError(
                    "multi_floor_stair_not_supported",
                    "the facade editor does not yet preserve separate floor, stair and roof "
                    "scene bodies; edit this stair house only after multi-floor facade support",
                )
            return house
        if job.type == FACADE_JOB and isinstance(job.input.get("promoted_from_scan"), dict):
            request = _facade_request(job)
            return HouseBoxRequest(
                length_mm=request.length_mm,
                width_mm=request.width_mm,
                floor_height_mm=request.floor_height_mm,
                floors=request.floors,
                shape="rectangle",
            )
        source_id = job.input.get("version_id")
        source = db.get(ProjectVersion, uuid.UUID(str(source_id))) if source_id else None
        if (
            source is None
            or source.project_id != current.project_id
            or source.id != current.parent_version_id
        ):
            break
        current = source
    raise IneligibleVersionError(
        "broken_lineage",
        "the facade editor needs a rectangular house-box version; its facade lineage "
        "could not be traced back to one",
    )


def _facade_request(job: Job | None) -> FacadeRequest:
    if job is None or job.type != FACADE_JOB:
        raise ValidationFailedError("this version is not a saved facade variant")
    try:
        return FacadeRequest(**dict(job.input.get("request") or {}))
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationFailedError("the saved facade request is invalid") from exc


def _overhang_value(prompt: str, current_value_mm: float) -> float:
    cleaned = " ".join(prompt.strip().split())
    match = None
    for pattern in _OVERHANG_PATTERNS:
        match = pattern.fullmatch(cleaned)
        if match is not None:
            break
    if match is None:
        raise ValidationFailedError(
            "only an explicit roof-overhang target is supported here",
            {
                "examples": [
                    "Увеличь свес крыши до 400 мм",
                    "Set roof overhang to 400 mm",
                ]
            },
        )
    value = float(match.group("value").replace(",", "."))
    unit = match.group("unit").lower()
    multiplier = 1.0 if unit in ("мм", "mm") else 10.0 if unit in ("см", "cm") else 1_000.0
    value_mm = value * multiplier
    direction = match.groupdict().get("direction", "").lower()
    if direction:
        value_mm = (
            current_value_mm + value_mm
            if direction in ("увеличь", "increase")
            else current_value_mm - value_mm
        )
    if not math.isfinite(value_mm) or not 0 <= value_mm <= 2_000:
        raise ValidationFailedError(
            "roof overhang must be between 0 and 2000 mm", {"new_value_mm": value_mm}
        )
    return value_mm


def _wall_thickness_value(prompt: str, current_value_mm: float) -> float:
    cleaned = " ".join(prompt.strip().split())
    match = None
    for pattern in _WALL_THICKNESS_PATTERNS:
        match = pattern.fullmatch(cleaned)
        if match is not None:
            break
    if match is None:
        raise ValidationFailedError(
            "only an explicit wall-thickness target is supported here",
            {
                "examples": [
                    "Измени толщину стен до 300 мм",
                    "Set wall thickness to 300 mm",
                ]
            },
        )
    value = float(match.group("value").replace(",", "."))
    unit = match.group("unit").lower()
    multiplier = 1.0 if unit in ("мм", "mm") else 10.0 if unit in ("см", "cm") else 1_000.0
    value_mm = value * multiplier
    direction = match.groupdict().get("direction", "").lower()
    if direction:
        value_mm = (
            current_value_mm + value_mm
            if direction in ("увеличь", "increase")
            else current_value_mm - value_mm
        )
    if not math.isfinite(value_mm) or not 100 <= value_mm <= 600:
        raise ValidationFailedError(
            "wall thickness must be between 100 and 600 mm", {"new_value_mm": value_mm}
        )
    return value_mm


def _roof_height_value(prompt: str, current_value_mm: float) -> float:
    cleaned = " ".join(prompt.strip().split())
    match = None
    for pattern in _ROOF_HEIGHT_PATTERNS:
        match = pattern.fullmatch(cleaned)
        if match is not None:
            break
    if match is None:
        raise ValidationFailedError(
            "only an explicit roof-height target is supported here",
            {
                "examples": [
                    "Увеличь высоту крыши до 1500 мм",
                    "Set roof height to 1500 mm",
                ]
            },
        )
    value = float(match.group("value").replace(",", "."))
    unit = match.group("unit").lower()
    multiplier = 1.0 if unit in ("мм", "mm") else 10.0 if unit in ("см", "cm") else 1_000.0
    value_mm = value * multiplier
    direction = match.groupdict().get("direction", "").lower()
    if direction:
        value_mm = (
            current_value_mm + value_mm
            if direction in ("увеличь", "increase")
            else current_value_mm - value_mm
        )
    if not math.isfinite(value_mm) or not 200 <= value_mm <= 5_000:
        raise ValidationFailedError(
            "roof height must be between 200 and 5000 mm", {"new_value_mm": value_mm}
        )
    return value_mm


def _dimension_value(
    prompt: str,
    current_value_mm: float,
    *,
    patterns: tuple[re.Pattern[str], ...],
    minimum_mm: float,
    maximum_mm: float,
    parameter: str,
    examples: list[str],
) -> float:
    cleaned = " ".join(prompt.strip().split())
    match = None
    for pattern in patterns:
        match = pattern.fullmatch(cleaned)
        if match is not None:
            break
    if match is None:
        raise ValidationFailedError(
            f"only an explicit {parameter} target is supported here",
            {"examples": examples},
        )
    value = float(match.group("value").replace(",", "."))
    unit = match.group("unit").lower()
    multiplier = 1.0 if unit in ("мм", "mm") else 10.0 if unit in ("см", "cm") else 1_000.0
    value_mm = value * multiplier
    direction = match.groupdict().get("direction", "").lower()
    if direction:
        value_mm = (
            current_value_mm + value_mm
            if direction in ("увеличь", "increase")
            else current_value_mm - value_mm
        )
    if not math.isfinite(value_mm) or not minimum_mm <= value_mm <= maximum_mm:
        raise ValidationFailedError(
            f"{parameter} must be between {minimum_mm:g} and {maximum_mm:g} mm",
            {"new_value_mm": value_mm},
        )
    return value_mm


def _command_change(db: Session, version: ProjectVersion, prompt: str) -> FacadeCommandChange:
    current = _facade_request(_producing_job(db, version))
    cleaned = " ".join(prompt.strip().split())
    if re.search(
        r"(?:длин(?:а|у|ы)\s+(?:дома|здания)|(?:house|building)\s+length)",
        cleaned,
        re.IGNORECASE,
    ):
        parameter: FacadeCommandParameter = "house_length"
        field = "length_mm"
        label_ru = "Длина дома"
        label_en = "House length"
        current_value = getattr(current, field)
        new_value = _dimension_value(
            cleaned,
            current_value,
            patterns=_HOUSE_LENGTH_PATTERNS,
            minimum_mm=2_000,
            maximum_mm=50_000,
            parameter="house length",
            examples=["Измени длину дома до 12 м", "Set house length to 12 m"],
        )
    elif re.search(
        r"(?:ширин(?:а|у|ы)\s+(?:дома|здания)|(?:house|building)\s+width)",
        cleaned,
        re.IGNORECASE,
    ):
        parameter = "house_width"
        field = "width_mm"
        label_ru = "Ширина дома"
        label_en = "House width"
        current_value = getattr(current, field)
        new_value = _dimension_value(
            cleaned,
            current_value,
            patterns=_HOUSE_WIDTH_PATTERNS,
            minimum_mm=2_000,
            maximum_mm=50_000,
            parameter="house width",
            examples=["Измени ширину дома до 8 м", "Set house width to 8 m"],
        )
    elif re.search(
        r"(?:высот(?:а|у|ы)\s+(?:этажа|стен)|(?:floor|storey|story|wall)\s+height)",
        cleaned,
        re.IGNORECASE,
    ):
        parameter = "floor_height"
        field = "floor_height_mm"
        label_ru = "Высота этажа"
        label_en = "Floor height"
        current_value = getattr(current, field)
        new_value = _dimension_value(
            cleaned,
            current_value,
            patterns=_FLOOR_HEIGHT_PATTERNS,
            minimum_mm=2_200,
            maximum_mm=6_000,
            parameter="floor height",
            examples=["Увеличь высоту этажа до 3 м", "Set floor height to 3 m"],
        )
    elif re.search(
        r"(?:толщин(?:а|у|ы)\s+(?:стены|стен)|wall\s+thickness)",
        cleaned,
        re.IGNORECASE,
    ):
        parameter = "wall_thickness"
        field = "wall_thickness_mm"
        label_ru = "Толщина стен"
        label_en = "Wall thickness"
        current_value = getattr(current, field)
        new_value = _wall_thickness_value(cleaned, current_value)
    elif re.search(r"(?:высот(?:а|у|ы)\s+крыши|roof\s+height)", cleaned, re.IGNORECASE):
        parameter = "roof_height"
        field = "roof_height_mm"
        label_ru = "Высота крыши"
        label_en = "Roof height"
        current_value = getattr(current, field)
        new_value = _roof_height_value(cleaned, current_value)
        if current.roof == "none":
            raise ValidationFailedError(
                "roof height cannot be changed because this facade has no roof",
                {"reason": "roof_missing"},
            )
    else:
        parameter = "roof_overhang"
        field = "overhang_mm"
        label_ru = "Свес крыши"
        label_en = "Roof overhang"
        current_value = getattr(current, field)
        new_value = _overhang_value(cleaned, current_value)
        if current.roof == "none":
            raise ValidationFailedError(
                "roof overhang cannot be changed because this facade has no roof",
                {"reason": "roof_missing"},
            )
    if math.isclose(current_value, new_value, abs_tol=1e-9):
        raise ValidationFailedError(
            f"{label_en.lower()} is already set to this value",
            {"current_value_mm": current_value},
        )
    try:
        changed = current.__class__(
            **{
                **FACADE_ADAPTER.dump_python(current, mode="python"),
                field: new_value,
            }
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationFailedError(str(exc), {"new_value_mm": new_value}) from exc
    return FacadeCommandChange(
        request=changed,
        parameter=parameter,
        label_ru=label_ru,
        label_en=label_en,
        current_value_mm=current_value,
        new_value_mm=new_value,
    )


def _edit_body(request: FacadeRequest) -> FacadeEditBody:
    payload = FACADE_ADAPTER.dump_python(request, mode="json", exclude_none=True)
    payload.pop("floors", None)
    return FacadeEditBody.model_validate(payload)


def _variant_name(job: Job | None) -> str | None:
    raw = job.input.get("variant_name") if job is not None else None
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    return cleaned if cleaned else None


def _validate_materials(db: Session, assignments: list[SurfaceMaterial]) -> None:
    for assignment in assignments:
        if assignment.material_id is not None and db.get(Material, assignment.material_id) is None:
            raise ValidationFailedError(
                f"unknown material {assignment.material_id!r}",
                {"hint": "GET /api/v1/materials"},
            )


def _variant_out(version: ProjectVersion, job: Job, request: FacadeRequest) -> FacadeVariantOut:
    name = _variant_name(job)
    assert name is not None
    estimate = variant_estimate(request)
    return FacadeVariantOut(
        version_id=version.id,
        sequence_no=version.sequence_no,
        name=name,
        created_at=version.created_at,
        surface_keys=sorted(surface_keys(request)),
        surface_assignments=[
            SurfaceMaterialBody.model_validate(SURFACE_ADAPTER.dump_python(item, mode="json"))
            for item in request.surface_assignments
        ],
        category_areas_m2=estimate["category_areas_m2"],
        assigned_area_m2=estimate["assigned_area_m2"],
        priced_area_m2=estimate["priced_area_m2"],
        unpriced_assigned_area_m2=estimate["unpriced_assigned_area_m2"],
        estimated_cost=estimate["estimated_cost"],
        currency=estimate["currency"],
    )


@router.get("/projects/{project_id}/facade-variants", response_model=list[FacadeVariantOut])
def list_facade_variants(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[FacadeVariantOut]:
    """Named immutable facade finishes, newest first, with analytic quantities and estimate."""
    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    variants: list[FacadeVariantOut] = []
    for version in projects.list_versions(
        db, user_id=principal.user_id, project_id=project_id, limit=500
    ):
        job = _producing_job(db, version)
        if job is None or _variant_name(job) is None:
            continue
        variants.append(_variant_out(version, job, _facade_request(job)))
    return variants


@router.post(
    "/models/{version_id}/facade-from-scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_facade_from_scan(
    version_id: uuid.UUID,
    body: ScannedFacadeBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """Replace a scan's noisy exterior with an explicit exact semantic facade draft."""
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    if project.head_version_id != version.id:
        raise ConflictError(
            "the scanned facade changed; reload before rebuilding it",
            {"head_version_id": str(project.head_version_id)},
        )
    scan = _scan_ancestor(db, version)
    if (
        scan is None
        or scan.mesh_asset_id is None
        or (scan.capabilities or {}).get("subject") != "exterior"
    ):
        raise ValidationFailedError(
            "this version does not descend from an accepted exterior scan",
            {"reason": "not_exterior_scan"},
        )
    try:
        openings = []
        for index, item in enumerate(body.openings):
            payload = item.model_dump(exclude_none=True)
            if item.opening_id is None:
                payload["opening_id"] = opening_key(FacadeOpening(**payload), index)
            openings.append(FacadeOpening(**payload))
        request = FacadeRequest(
            length_mm=body.length_mm,
            width_mm=body.width_mm,
            floor_height_mm=body.floor_height_mm,
            floors=body.floors,
            wall_thickness_mm=body.wall_thickness_mm,
            roof=body.roof,
            roof_height_mm=body.roof_height_mm,
            overhang_mm=body.overhang_mm,
            openings=openings,
            surface_assignments=[
                SurfaceMaterial(surface_key=f"wall.{side}", colour=body.wall_colour)
                for side in ("front", "back", "left", "right")
            ],
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationFailedError(str(exc)) from exc
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=FACADE_JOB,
        input={
            "version_id": str(version.id),
            "request": FACADE_ADAPTER.dump_python(request, mode="json", exclude_none=True),
            "preserve_scan_asset_id": str(scan.mesh_asset_id),
            "require_head_version": True,
            "promoted_from_scan": {
                "scan_session_id": str(scan.id),
                "accepted_version_id": str(scan.result_version_id),
                "source_version_id": str(version.id),
                "method": "manual_metric_facade_trace",
            },
        },
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/facade-command-proposal",
    response_model=FacadeCommandProposalOut,
)
def propose_facade_command(
    version_id: uuid.UUID,
    body: FacadeCommandProposalBody,
    db: DbDep,
    principal: PrincipalDep,
) -> FacadeCommandProposalOut:
    """Parse one bounded named facade edit without enqueueing or spending an AI job."""
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    change = _command_change(db, version, body.prompt)
    return FacadeCommandProposalOut(
        source_version_id=version.id,
        parameter=change.parameter,
        label_ru=change.label_ru,
        label_en=change.label_en,
        current_value_mm=change.current_value_mm,
        new_value_mm=change.new_value_mm,
    )


@router.post(
    "/models/{version_id}/facade",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def edit_facade(
    version_id: uuid.UUID,
    body: FacadeEditBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    try:
        house = _rectangular_house(db, version)
    except IneligibleVersionError as exc:
        raise ValidationFailedError(
            str(exc), {"version_id": str(version.id), "reason": exc.reason}
        ) from exc
    parent_job = _producing_job(db, version)
    parent_request = (
        _facade_request(parent_job)
        if parent_job is not None and parent_job.type == FACADE_JOB
        else None
    )
    parent_assignments: list[dict[str, str | None]] = []
    if parent_job is not None and parent_job.type == FACADE_JOB:
        raw_parent = dict(parent_job.input.get("request") or {}).get("surface_assignments") or []
        if isinstance(raw_parent, list):
            parent_assignments = [dict(item) for item in raw_parent if isinstance(item, dict)]
    requested_assignments = (
        [item.model_dump(mode="json", exclude_none=True) for item in body.surface_assignments]
        if body.surface_assignments is not None
        else parent_assignments
    )
    for assignment in requested_assignments:
        material_id = assignment.get("material_id")
        if material_id is not None and db.get(Material, material_id) is None:
            raise ValidationFailedError(
                f"unknown material {material_id!r}", {"hint": "GET /api/v1/materials"}
            )
    try:
        openings: list[FacadeOpening] = []
        for index, item in enumerate(body.openings):
            payload = item.model_dump(exclude_none=True)
            if item.opening_id is None:
                payload["opening_id"] = opening_key(FacadeOpening(**payload), index)
            openings.append(FacadeOpening(**payload))
        base_request = FacadeRequest(
            length_mm=(
                body.length_mm
                if body.length_mm is not None
                else parent_request.length_mm
                if parent_request is not None
                else house.length_mm
            ),
            width_mm=(
                body.width_mm
                if body.width_mm is not None
                else parent_request.width_mm
                if parent_request is not None
                else house.width_mm
            ),
            floor_height_mm=(
                body.floor_height_mm
                if body.floor_height_mm is not None
                else parent_request.floor_height_mm
                if parent_request is not None
                else house.floor_height_mm
            ),
            floors=house.floors,
            wall_thickness_mm=body.wall_thickness_mm,
            roof=body.roof,
            roof_height_mm=body.roof_height_mm,
            overhang_mm=body.overhang_mm,
            openings=openings,
        )
        current_keys = surface_keys(base_request)
        if body.surface_assignments is None:
            requested_assignments = [
                item for item in requested_assignments if item.get("surface_key") in current_keys
            ]
        request = FacadeRequest(
            **FACADE_ADAPTER.dump_python(
                base_request, mode="python", exclude={"surface_assignments"}
            ),
            surface_assignments=[SurfaceMaterial(**item) for item in requested_assignments],
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationFailedError(str(exc)) from exc
    dropped = sorted(
        str(assignment["surface_key"])
        for assignment in parent_assignments
        if assignment.get("surface_key") not in current_keys
    )
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=FACADE_JOB,
        input={
            "version_id": str(version.id),
            "request": FACADE_ADAPTER.dump_python(request, mode="json", exclude_none=True),
            "dropped_surface_assignments": dropped,
            **({"variant_name": body.variant_name} if body.variant_name is not None else {}),
        },
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/facade-command-apply",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def apply_facade_command(
    version_id: uuid.UUID,
    body: FacadeCommandApplyBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """Re-derive and apply the exact proposal; modified or stale proposal fields fail closed."""
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    change = _command_change(db, version, body.prompt)
    if not math.isclose(change.current_value_mm, body.expected_current_mm, abs_tol=1e-9):
        raise ValidationFailedError(
            "the proposal current value does not match its source version",
            {
                "expected_current_mm": body.expected_current_mm,
                "actual_current_mm": change.current_value_mm,
            },
        )
    if not math.isclose(change.new_value_mm, body.proposed_new_mm, abs_tol=1e-9):
        raise ValidationFailedError(
            "the proposal target does not match the command",
            {"proposed_new_mm": body.proposed_new_mm, "parsed_new_mm": change.new_value_mm},
        )
    return edit_facade(
        version_id,
        _edit_body(change.request),
        db,
        principal,
        idempotency_key,
    )


@router.post(
    "/models/{version_id}/facade-variant",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def apply_facade_variant(
    version_id: uuid.UUID,
    body: FacadeVariantApplyBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """Apply only a named variant's finishes to matching current facade geometry."""
    target = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=target.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    target_job = _producing_job(db, target)
    if target_job is None or target_job.type != FACADE_JOB:
        raise ValidationFailedError(
            "apply a saved finish variant to an existing facade version",
            {"reason": "target_has_no_facade"},
        )
    source = db.get(ProjectVersion, body.variant_version_id)
    if source is None or source.project_id != target.project_id:
        raise NotFoundError("facade_variant", body.variant_version_id)
    source_job = _producing_job(db, source)
    name = _variant_name(source_job)
    if name is None:
        raise NotFoundError("facade_variant", body.variant_version_id)
    target_request = _facade_request(target_job)
    source_request = _facade_request(source_job)
    target_keys = surface_keys(target_request)
    source_keys = surface_keys(source_request)
    if target_keys != source_keys:
        raise ValidationFailedError(
            "the saved variant does not match this facade's roof and openings",
            {
                "reason": "surface_set_mismatch",
                "missing_surface_keys": sorted(source_keys - target_keys),
                "extra_surface_keys": sorted(target_keys - source_keys),
            },
        )
    payload = FACADE_ADAPTER.dump_python(target_request, mode="python")
    payload["surface_assignments"] = [
        SURFACE_ADAPTER.dump_python(item, mode="python")
        for item in source_request.surface_assignments
    ]
    request = FacadeRequest(**payload)
    _validate_materials(db, request.surface_assignments)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=target.id,
        job_type=FACADE_JOB,
        input={
            "version_id": str(target.id),
            "request": FACADE_ADAPTER.dump_python(request, mode="json", exclude_none=True),
            "dropped_surface_assignments": [],
            "applied_variant": {
                "name": name,
                "version_id": str(source.id),
            },
        },
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
