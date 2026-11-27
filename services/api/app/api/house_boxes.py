"""Quick-start house massing wizard API."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator
from sqlalchemy.orm import Session

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering.house_box import (
    HouseBoxRequest,
    LTurnStairRequest,
    SpiralStairRequest,
    StairRequest,
    StraightStairRequest,
    UpperFloorSetbackSides,
    UTurnStairRequest,
    WinderTurnStairRequest,
    stair_kind,
)
from app.engineering.house_text import HouseTextError, ParsedHouseText, parse_house_text
from app.interior_materials import material_by_id
from app.models.core import WorkspaceRole
from app.services import house_boxes, projects
from app.services.authz import require_workspace_role

router = APIRouter(tags=["house-design"])


class StraightStairBody(BaseModel):
    kind: Literal["straight"] = "straight"
    width_mm: float = Field(default=1_000, ge=700, le=2_000)
    tread_depth_mm: float = Field(default=280, ge=200, le=400)
    step_count: int = Field(default=17, ge=10, le=30)
    placement: Literal["left", "center", "right"] = "center"
    railing: bool = True
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class LTurnStairBody(BaseModel):
    """Two flights and one square quarter-turn landing; the landing counts as one riser.

    Unknown fields are rejected so a straight-stair ``step_count`` cannot be silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["l_turn"]
    width_mm: float = Field(default=1_000, ge=700, le=2_000)
    tread_depth_mm: float = Field(default=280, ge=200, le=400)
    lower_step_count: int = Field(default=8, ge=3, le=26)
    upper_step_count: int = Field(default=8, ge=3, le=26)
    turn: Literal["left", "right"] = "left"
    placement: Literal["left", "center", "right"] = "center"
    railing: bool = True
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class UTurnStairBody(BaseModel):
    """Two equal parallel flights and one half-turn landing spanning both flights."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["u_turn"]
    width_mm: float = Field(default=1_000, ge=700, le=2_000)
    tread_depth_mm: float = Field(default=280, ge=200, le=400)
    flight_step_count: int = Field(default=8, ge=5, le=14)
    turn: Literal["left", "right"] = "left"
    placement: Literal["left", "center", "right"] = "center"
    railing: bool = True
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class WinderTurnStairBody(BaseModel):
    """Two perpendicular flights and exactly three 30° winder treads around an open newel square.

    Values are strict (no string/boolean coercion), unknown fields are rejected and ``railing``
    accepts only ``false`` because rails along a winder turn are not modelled.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["winder_turn"]
    width_mm: float = Field(default=1_000, ge=700, le=2_000, strict=True, allow_inf_nan=False)
    tread_depth_mm: float = Field(default=280, ge=200, le=400, strict=True, allow_inf_nan=False)
    lower_step_count: int = Field(default=7, ge=3, le=24, strict=True)
    upper_step_count: int = Field(default=7, ge=3, le=24, strict=True)
    newel_mm: float = Field(default=250, ge=200, le=500, strict=True, allow_inf_nan=False)
    turn: Literal["left", "right"] = "left"
    placement: Literal["left", "center", "right"] = "center"
    railing: Literal[False] = False
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class SpiralStairBody(BaseModel):
    """Equal circular-sector treads around a central post, sweeping ``sweep_deg`` in total.

    Values are strict (no string/boolean coercion), unknown fields are rejected and ``railing``
    accepts only ``false`` because rails along a helix are not modelled.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["spiral"]
    diameter_mm: float = Field(default=2_200, ge=1_400, le=3_200, strict=True, allow_inf_nan=False)
    post_diameter_mm: float = Field(default=200, ge=100, le=300, strict=True, allow_inf_nan=False)
    step_count: int = Field(default=15, ge=10, le=20, strict=True)
    sweep_deg: float = Field(default=300, ge=180, le=330, strict=True, allow_inf_nan=False)
    turn: Literal["left", "right"] = "left"
    placement: Literal["left", "center", "right"] = "center"
    railing: Literal[False] = False
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


StairBody = Annotated[
    Annotated[StraightStairBody, Tag("straight")]
    | Annotated[LTurnStairBody, Tag("l_turn")]
    | Annotated[UTurnStairBody, Tag("u_turn")]
    | Annotated[WinderTurnStairBody, Tag("winder_turn")]
    | Annotated[SpiralStairBody, Tag("spiral")],
    Discriminator(stair_kind),
]


def _stair_request(body: StairBody) -> StairRequest:
    if isinstance(body, LTurnStairBody):
        return LTurnStairRequest(**body.model_dump())
    if isinstance(body, UTurnStairBody):
        return UTurnStairRequest(**body.model_dump())
    if isinstance(body, WinderTurnStairBody):
        return WinderTurnStairRequest(**body.model_dump())
    if isinstance(body, SpiralStairBody):
        return SpiralStairRequest(**body.model_dump())
    return StraightStairRequest(**body.model_dump())


class UpperFloorSetbackSidesBody(BaseModel):
    """Per-wall inset of every upper floor and the roof; X along the length, Y across it."""

    model_config = ConfigDict(extra="forbid")

    x_min_mm: float = Field(default=0, ge=0, le=10_000, strict=True, allow_inf_nan=False)
    x_max_mm: float = Field(default=0, ge=0, le=10_000, strict=True, allow_inf_nan=False)
    y_min_mm: float = Field(default=0, ge=0, le=10_000, strict=True, allow_inf_nan=False)
    y_max_mm: float = Field(default=0, ge=0, le=10_000, strict=True, allow_inf_nan=False)


class HouseBoxBody(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)
    length_mm: float = Field(ge=2_000, le=50_000)
    width_mm: float = Field(ge=2_000, le=50_000)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)
    shape: Literal["rectangle", "l_shape", "t_shape"] = "rectangle"
    stair: StairBody | None = None
    # Optional transition-specific stairs, 1→2 first. The domain layer enforces floors - 1.
    stairs: list[StairBody] | None = Field(default=None, min_length=1, max_length=2)
    upper_floor_setback_mm: float = Field(default=0, ge=0, le=10_000)
    upper_floor_setback_sides_mm: UpperFloorSetbackSidesBody | None = None
    # Exactly ``floors - 1`` entries, floor 2 first; the roof repeats the top floor.
    upper_floor_setbacks_mm: list[UpperFloorSetbackSidesBody] | None = Field(
        default=None, min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def one_stair_mode(self) -> "HouseBoxBody":
        if self.stair is not None and self.stairs is not None:
            raise ValueError("use either stair or stairs, not both")
        return self


class HouseBoxAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    height_mm: float
    shape: Literal["rectangle", "l_shape", "t_shape"]


@router.post("/house-boxes", status_code=status.HTTP_202_ACCEPTED, response_model=HouseBoxAccepted)
def build_house_box(
    body: HouseBoxBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> HouseBoxAccepted:
    for stair in [body.stair] if body.stair is not None else body.stairs or []:
        if stair.material_id is not None:
            material_by_id(stair.material_id)
    try:
        request = HouseBoxRequest(
            length_mm=body.length_mm,
            width_mm=body.width_mm,
            floor_height_mm=body.floor_height_mm,
            floors=body.floors,
            shape=body.shape,
            stair=_stair_request(body.stair) if body.stair is not None else None,
            stairs=(tuple(_stair_request(stair) for stair in body.stairs) if body.stairs else None),
            upper_floor_setback_mm=body.upper_floor_setback_mm,
            upper_floor_setback_sides_mm=(
                UpperFloorSetbackSides(**body.upper_floor_setback_sides_mm.model_dump())
                if body.upper_floor_setback_sides_mm is not None
                else None
            ),
            upper_floor_setbacks_mm=(
                tuple(
                    UpperFloorSetbackSides(**level.model_dump())
                    for level in body.upper_floor_setbacks_mm
                )
                if body.upper_floor_setbacks_mm is not None
                else None
            ),
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    job, project_id = house_boxes.enqueue_house_box(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        request=request,
        project_id=body.project_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return HouseBoxAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        height_mm=request.floor_height_mm * request.floors,
        shape=request.shape,
    )


class HouseTextRequestBody(BaseModel):
    """The canonical request a text proposal may produce: whole mm, bounded shape, no stair."""

    model_config = ConfigDict(extra="forbid", strict=True)

    length_mm: int = Field(ge=2_000, le=50_000)
    width_mm: int = Field(ge=2_000, le=50_000)
    floor_height_mm: int = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)
    shape: Literal["rectangle", "l_shape", "t_shape"] = "rectangle"


class HouseTextProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    prompt: str = Field(min_length=1, max_length=500)


class HouseTextApplyBody(HouseTextProposalBody):
    request: HouseTextRequestBody


HouseTextField = Literal["length_mm", "width_mm", "floor_height_mm", "floors", "shape"]


class HouseTextDiffEntry(BaseModel):
    field: HouseTextField
    label_ru: str
    label_en: str
    before: None = None
    after: int | Literal["rectangle", "l_shape", "t_shape"]
    unit: Literal["mm", "count", "enum"]
    source: str | None


class HouseTextProposalOut(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None
    language: Literal["ru", "en"]
    request: HouseTextRequestBody
    diff: list[HouseTextDiffEntry]
    total_height_mm: int
    footprint_area_m2: float
    summary_ru: str
    summary_en: str
    job_created: Literal[False] = False
    ai_used: Literal[False] = False


_TEXT_LABELS: dict[HouseTextField, tuple[str, str, Literal["mm", "count", "enum"]]] = {
    "length_mm": ("Длина", "Length", "mm"),
    "width_mm": ("Ширина", "Width", "mm"),
    "floor_height_mm": ("Высота этажа", "Floor height", "mm"),
    "floors": ("Этажей", "Floors", "count"),
    "shape": ("Форма", "Shape", "enum"),
}


def _parsed(prompt: str) -> ParsedHouseText:
    try:
        return parse_house_text(prompt)
    except HouseTextError as exc:
        raise ValidationFailedError(exc.message, exc.details) from exc


def _text_target(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID, project_id: uuid.UUID | None
) -> None:
    """Workspace editor; an optional target project must be in that workspace and still empty.

    A described house is a new immutable lineage root, so it never lands on top of an
    existing head; a head appearing between proposal and apply is a conflict.
    """
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if project_id is None:
        return
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    if project.workspace_id != workspace_id:
        raise NotFoundError("project", project_id)
    if project.head_version_id is not None:
        raise ConflictError(
            "a house from a description can only start an empty project",
            {"reason": "project_has_head", "head_version_id": str(project.head_version_id)},
        )


def _canonical(parsed: ParsedHouseText) -> HouseBoxRequest:
    try:
        return HouseBoxRequest(**parsed.request())
    except ValueError as exc:
        raise ValidationFailedError(str(exc), {"reason": "invalid_house_box"}) from exc


def _number(value: int, language: Literal["ru", "en"]) -> str:
    return f"{value:,}".replace(",", "\u00a0" if language == "ru" else ",")


def _proposal(body: HouseTextProposalBody, parsed: ParsedHouseText) -> HouseTextProposalOut:
    request = HouseTextRequestBody.model_validate(parsed.request())
    total = request.floor_height_mm * request.floors
    shape_ru = {
        "rectangle": "Прямоугольный",
        "l_shape": "Г-образный",
        "t_shape": "Т-образный",
    }[request.shape]
    shape_en = {
        "rectangle": "Rectangular",
        "l_shape": "L-shaped",
        "t_shape": "T-shaped",
    }[request.shape]
    area_ratio = {"rectangle": 1.0, "l_shape": 0.75, "t_shape": 5 / 9}[request.shape]
    ru = (
        f"{shape_ru} дом {_number(request.length_mm, 'ru')} × "
        f"{_number(request.width_mm, 'ru')} мм, этажей: {request.floors}, высота этажа "
        f"{_number(request.floor_height_mm, 'ru')} мм, общая высота {_number(total, 'ru')} мм"
    )
    en = (
        f"{shape_en} house {_number(request.length_mm, 'en')} × "
        f"{_number(request.width_mm, 'en')} mm, {request.floors} floor(s) of "
        f"{_number(request.floor_height_mm, 'en')} mm, total height {_number(total, 'en')} mm"
    )
    return HouseTextProposalOut(
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        language=parsed.language,
        request=request,
        diff=[
            HouseTextDiffEntry(
                field=name,
                label_ru=label_ru,
                label_en=label_en,
                after=getattr(request, name),
                unit=unit,
                source=parsed.sources.get(name),
            )
            for name, (label_ru, label_en, unit) in _TEXT_LABELS.items()
        ],
        total_height_mm=total,
        footprint_area_m2=round(request.length_mm * request.width_mm * area_ratio / 1_000_000, 3),
        summary_ru=ru,
        summary_en=en,
    )


@router.post("/house-boxes/text-proposal", response_model=HouseTextProposalOut)
def propose_house_from_text(
    body: HouseTextProposalBody,
    db: DbDep,
    principal: PrincipalDep,
) -> HouseTextProposalOut:
    """Item 41: parse a bounded description into a verifiable request; no job, no AI."""
    _text_target(db, principal.user_id, body.workspace_id, body.project_id)
    parsed = _parsed(body.prompt)
    _canonical(parsed)
    return _proposal(body, parsed)


@router.post(
    "/house-boxes/text-apply",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=HouseBoxAccepted,
)
def apply_house_from_text(
    body: HouseTextApplyBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> HouseBoxAccepted:
    """Re-parse the original text and enqueue only the exact confirmed request."""
    _text_target(db, principal.user_id, body.workspace_id, body.project_id)
    parsed = _parsed(body.prompt)
    expected = HouseTextRequestBody.model_validate(parsed.request())
    if body.request != expected:
        raise ValidationFailedError(
            "the confirmed proposal does not match the description",
            {
                "reason": "proposal_mismatch",
                "submitted": body.request.model_dump(),
                "parsed": expected.model_dump(),
            },
        )
    request = _canonical(parsed)
    job, project_id = house_boxes.enqueue_house_box(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        request=request,
        project_id=body.project_id,
        label="Дом по описанию" if parsed.language == "ru" else "House from description",
        idempotency_key=idempotency_key,
        source={"kind": "text_proposal", "prompt": body.prompt, "language": parsed.language},
    )
    return HouseBoxAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        height_mm=request.floor_height_mm * request.floors,
        shape=request.shape,
    )
