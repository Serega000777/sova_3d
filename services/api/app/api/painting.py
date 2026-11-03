"""Paint endpoints (T-108, F-034): colour a model without changing its shape."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import painting

router = APIRouter(tags=["paint"])

COLOUR = r"^#[0-9a-fA-F]{6}$"
LayerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class Stroke(BaseModel):
    """One swipe of colour. Without a region it covers the whole body."""

    model_config = ConfigDict(extra="forbid")

    colour: str | None = Field(default=None, pattern=COLOUR)
    catalog_material_id: str | None = Field(default=None, min_length=1, max_length=120)
    opacity: float = Field(default=1.0, ge=0.05, le=1.0)
    region: dict[str, Any] | None = None

    @model_validator(mode="after")
    def one_surface(self) -> Stroke:
        if (self.colour is None) == (self.catalog_material_id is None):
            raise ValueError("a stroke needs exactly one colour or catalogue material")
        if self.catalog_material_id is not None and self.opacity != 1.0:
            raise ValueError("catalogue material strokes are opaque")
        return self


class PaintBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strokes: list[Stroke] = Field(default_factory=list, max_length=painting.MAX_STROKES)
    base_colour: str | None = Field(default=None, pattern=COLOUR)
    label: str | None = Field(default=None, max_length=200)
    layer_name: str | None = Field(default=None, max_length=80)
    # By default new strokes go on top of the paint the version already has.
    replace: bool = False

    @field_validator("layer_name")
    @classmethod
    def clean_layer_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("layer_name must not be blank")
        return cleaned


@router.post(
    "/models/{version_id}/paint",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def paint_model(
    version_id: uuid.UUID,
    body: PaintBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = painting.enqueue_paint(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        strokes=[stroke.model_dump(exclude_none=True) for stroke in body.strokes],
        base_colour=body.base_colour,
        label=body.label,
        layer_name=body.layer_name,
        replace=body.replace,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


class PaintLayerReorderBody(BaseModel):
    layer_order: list[LayerName] = Field(min_length=1, max_length=64)

    @field_validator("layer_order")
    @classmethod
    def names_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("layer_order must not repeat a layer name")
        return value


@router.post(
    "/models/{version_id}/paint/reorder-layers",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def reorder_paint_layers(
    version_id: uuid.UUID,
    body: PaintLayerReorderBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = painting.reorder_layers(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        layer_order=body.layer_order,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
