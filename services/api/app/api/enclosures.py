"""Component catalogue (T-156, F-035) and the enclosure generator (T-157, F-036)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.engineering import components as catalogue
from app.services import component_library, enclosures

router = APIRouter(tags=["components"])


class ComponentOut(BaseModel):
    id: str
    name: str
    kind: str
    size_mm: list[float]
    height_mm: float
    holes: list[dict[str, float]]
    screw: str
    cutouts: list[dict[str, Any]]
    opening_mm: list[float] | None
    standoff_mm: float
    confidence: str
    note: str
    aliases: list[str]
    model_scope: Literal["mounting_geometry"]


@router.get("/components", response_model=list[ComponentOut])
def list_components(
    q: str | None = Query(default=None, max_length=100),
    language: str = Query(default="en", pattern="^(en|ru)$"),
) -> list[ComponentOut]:
    """Real components the platform knows the geometry of: boards, fans, displays, motors."""
    return [ComponentOut(**catalogue.describe(c, language)) for c in catalogue.search(q, limit=100)]


class ComponentFavoritesOut(BaseModel):
    component_ids: list[str]


class ComponentFavoriteOut(BaseModel):
    component_id: str


@router.get("/components/favorites", response_model=ComponentFavoritesOut)
def list_component_favorites(db: DbDep, principal: PrincipalDep) -> ComponentFavoritesOut:
    return ComponentFavoritesOut(
        component_ids=component_library.favorite_ids(db, user_id=principal.user_id)
    )


@router.post("/components/favorites/{component_id}", response_model=ComponentFavoriteOut)
def add_component_favorite(
    component_id: str, db: DbDep, principal: PrincipalDep
) -> ComponentFavoriteOut:
    return ComponentFavoriteOut(
        component_id=component_library.add_favorite(
            db, user_id=principal.user_id, component_id=component_id
        )
    )


@router.delete("/components/favorites/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_component_favorite(component_id: str, db: DbDep, principal: PrincipalDep) -> None:
    component_library.remove_favorite(db, user_id=principal.user_id, component_id=component_id)


class ComponentModelBody(BaseModel):
    workspace_id: uuid.UUID
    label: str | None = Field(default=None, min_length=1, max_length=200)


class ComponentModelAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    component_id: str
    model_scope: Literal["mounting_geometry"] = "mounting_geometry"


@router.post(
    "/components/{component_id}/models",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ComponentModelAccepted,
)
def create_component_model(
    component_id: str,
    body: ComponentModelBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> ComponentModelAccepted:
    job, project_id = component_library.create_mounting_model(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        component_id=component_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return ComponentModelAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        component_id=component_id,
    )


class EnclosureBody(BaseModel):
    """A case around a component from the catalogue; every number is a plan parameter."""

    component_id: str = Field(max_length=64)
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None  # a new project named after the component when unset
    label: str | None = Field(default=None, max_length=200)
    wall_mm: float = Field(default=2.0, ge=1.0, le=6.0)
    clearance_mm: float = Field(default=1.0, ge=0.2, le=5.0)
    headroom_mm: float = Field(default=2.0, ge=0.0, le=30.0)
    lid: bool = True
    fan_id: str | None = Field(default=None, max_length=64)
    vents: bool = True
    corner_radius_mm: float = Field(default=2.0, ge=0.0, le=5.0)
    material_id: str | None = Field(default=None, max_length=64)


class EnclosureAccepted(BaseModel):
    job: JobAccepted
    project_id: uuid.UUID
    outer_mm: list[float]
    inner_mm: list[float]
    posts: int
    cutouts: list[str]
    lid: bool
    fan: str | None
    notes: list[str]


@router.post("/enclosures", status_code=status.HTTP_202_ACCEPTED, response_model=EnclosureAccepted)
def build_enclosure(
    body: EnclosureBody, db: DbDep, principal: PrincipalDep, idempotency_key: IdempotencyKey = None
) -> EnclosureAccepted:
    request = enclosures.request_from(body.model_dump(mode="json"))
    job, project_id, built = enclosures.enqueue_enclosure(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        request=request,
        project_id=body.project_id,
        label=body.label,
        idempotency_key=idempotency_key,
    )
    return EnclosureAccepted(
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        project_id=project_id,
        outer_mm=list(built.outer_mm),
        inner_mm=list(built.inner_mm),
        posts=built.posts,
        cutouts=built.cutouts,
        lid=built.lid,
        fan=built.fan,
        notes=built.notes,
    )
