"""Quick-start house massing wizard API."""

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.engineering.house_box import HouseBoxRequest, StraightStairRequest
from app.engineering.house_text import HouseTextError, ParsedHouseText, parse_house_text
from app.interior_materials import material_by_id
from app.models.core import WorkspaceRole
from app.services import house_boxes, projects
from app.services.authz import require_workspace_role

router = APIRouter(tags=["house-design"])


class StraightStairBody(BaseModel):
    width_mm: float = Field(default=1_000, ge=700, le=2_000)
    tread_depth_mm: float = Field(default=280, ge=200, le=400)
    step_count: int = Field(default=17, ge=10, le=30)
    placement: Literal["left", "center", "right"] = "center"
    railing: bool = True
    material_id: str | None = Field(default=None, min_length=1, max_length=120)


class HouseBoxBody(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)
    length_mm: float = Field(ge=2_000, le=50_000)
    width_mm: float = Field(ge=2_000, le=50_000)
    floor_height_mm: float = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)
    shape: Literal["rectangle", "l_shape", "t_shape"] = "rectangle"
    stair: StraightStairBody | None = None


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
    if body.stair is not None and body.stair.material_id is not None:
        material_by_id(body.stair.material_id)
    try:
        request = HouseBoxRequest(
            length_mm=body.length_mm,
            width_mm=body.width_mm,
            floor_height_mm=body.floor_height_mm,
            floors=body.floors,
            shape=body.shape,
            stair=(
                StraightStairRequest(**body.stair.model_dump()) if body.stair is not None else None
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
    """The only canonical request a text proposal may produce: whole mm, rectangle, no stair."""

    model_config = ConfigDict(extra="forbid", strict=True)

    length_mm: int = Field(ge=2_000, le=50_000)
    width_mm: int = Field(ge=2_000, le=50_000)
    floor_height_mm: int = Field(ge=2_200, le=6_000)
    floors: int = Field(ge=1, le=3)
    shape: Literal["rectangle"] = "rectangle"


class HouseTextProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    prompt: str = Field(min_length=1, max_length=500)


class HouseTextApplyBody(HouseTextProposalBody):
    request: HouseTextRequestBody


class HouseTextDiffEntry(BaseModel):
    field: Literal["length_mm", "width_mm", "floor_height_mm", "floors", "shape"]
    label_ru: str
    label_en: str
    before: None = None
    after: int | Literal["rectangle"]
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


_TEXT_LABELS: dict[str, tuple[str, str, Literal["mm", "count", "enum"]]] = {
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
    ru = (
        f"Прямоугольный дом {_number(request.length_mm, 'ru')} × "
        f"{_number(request.width_mm, 'ru')} мм, этажей: {request.floors}, высота этажа "
        f"{_number(request.floor_height_mm, 'ru')} мм, общая высота {_number(total, 'ru')} мм"
    )
    en = (
        f"Rectangular house {_number(request.length_mm, 'en')} × "
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
        footprint_area_m2=round(request.length_mm * request.width_mm / 1_000_000, 3),
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
