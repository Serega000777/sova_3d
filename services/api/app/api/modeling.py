"""Manual modeling tools (T-173, F-061) and organic generation (F-001/F-075)."""

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, SettingsDep
from app.api.schemas import JobAccepted
from app.services import generation, modeling

router = APIRouter(tags=["modeling"])


class PrimitiveBody(BaseModel):
    kind: Literal["box", "cylinder", "sphere", "cone", "torus"]
    width_mm: float | None = Field(default=None, gt=0, le=100000)
    depth_mm: float | None = Field(default=None, gt=0, le=100000)
    height_mm: float | None = Field(default=None, gt=0, le=100000)
    diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    top_diameter_mm: float | None = Field(default=None, ge=0, le=100000)
    outer_diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    tube_diameter_mm: float | None = Field(default=None, gt=0, le=100000)
    axis: Literal["x", "y", "z"] = "z"
    centered: bool = True

    @model_validator(mode="after")
    def dimensions_for_shape(self) -> "PrimitiveBody":
        if self.kind == "box" and (self.width_mm is None or self.depth_mm is None):
            raise ValueError("a box needs width_mm and depth_mm")
        if self.kind in {"box", "cylinder", "cone"} and self.height_mm is None:
            raise ValueError(f"a {self.kind} needs height_mm")
        if self.kind in {"cylinder", "sphere", "cone"} and self.diameter_mm is None:
            raise ValueError(f"a {self.kind} needs diameter_mm")
        if self.kind == "torus":
            if self.outer_diameter_mm is None or self.tube_diameter_mm is None:
                raise ValueError("a torus needs outer_diameter_mm and tube_diameter_mm")
            if 2 * self.tube_diameter_mm >= self.outer_diameter_mm:
                raise ValueError("tube diameter must be less than half the outer diameter")
        return self


@router.post(
    "/projects/{project_id}/primitives",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_primitive(
    project_id: uuid.UUID,
    body: PrimitiveBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    plan = modeling.primitive_plan(**body.model_dump())
    job = modeling.start_with_primitive(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        plan=plan,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


class GenerateMeshBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=300)
    size_mm: float = Field(default=60.0, ge=5, le=1000)
    quality: Literal["fast", "quality"] = "fast"


class DrawingHole(BaseModel):
    x_mm: float = Field(ge=-50_000, le=50_000)
    y_mm: float = Field(ge=-50_000, le=50_000)
    diameter_mm: float = Field(gt=0, le=10_000)


class DimensionedDrawingBody(BaseModel):
    width_mm: float = Field(gt=0, le=100_000)
    height_mm: float = Field(gt=0, le=100_000)
    thickness_mm: float = Field(gt=0, le=10_000)
    corner_radius_mm: float = Field(default=0, ge=0, le=50_000)
    holes: list[DrawingHole] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def dimensions_fit(self) -> "DimensionedDrawingBody":
        limit = min(self.width_mm, self.height_mm) / 2
        if self.corner_radius_mm >= limit:
            raise ValueError("corner radius must be less than half the smaller outline dimension")
        for index, hole in enumerate(self.holes):
            hole_radius = hole.diameter_mm / 2
            if abs(hole.x_mm) + hole_radius >= self.width_mm / 2:
                raise ValueError(f"hole {index + 1} crosses the drawing width")
            if abs(hole.y_mm) + hole_radius >= self.height_mm / 2:
                raise ValueError(f"hole {index + 1} crosses the drawing height")
            if self.corner_radius_mm > 0:
                dx = max(abs(hole.x_mm) - (self.width_mm / 2 - self.corner_radius_mm), 0)
                dy = max(abs(hole.y_mm) - (self.height_mm / 2 - self.corner_radius_mm), 0)
                if (dx * dx + dy * dy) ** 0.5 + hole_radius >= self.corner_radius_mm:
                    raise ValueError(f"hole {index + 1} crosses a rounded corner")
        for index, left in enumerate(self.holes):
            for right in self.holes[index + 1 :]:
                distance = ((left.x_mm - right.x_mm) ** 2 + (left.y_mm - right.y_mm) ** 2) ** 0.5
                if distance <= (left.diameter_mm + right.diameter_mm) / 2:
                    raise ValueError("drawing holes overlap")
        return self


@router.post(
    "/projects/{project_id}/dimensioned-drawing",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_dimensioned_drawing(
    project_id: uuid.UUID,
    body: DimensionedDrawingBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    trace = body.model_dump(mode="json")
    plan = modeling.dimensioned_drawing_plan(**trace)
    job = modeling.start_from_dimensioned_drawing(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        plan=plan,
        trace=trace,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/projects/{project_id}/generate-mesh",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def generate_mesh(
    project_id: uuid.UUID,
    body: GenerateMeshBody,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """A figurine, animal or vase from words: a mesh version, not a parametric part."""
    job = generation.start_generation(
        db,
        settings=settings,
        user_id=principal.user_id,
        project_id=project_id,
        prompt=body.prompt,
        size_mm=body.size_mm,
        quality=body.quality,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
