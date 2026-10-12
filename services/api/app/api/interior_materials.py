"""Interior finish catalogue and immutable per-scene-object assignment."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api import scenes as scene_api
from app.api.deps import DbDep, PrincipalDep
from app.interior_materials import all_materials, material_by_id, texture_bytes
from app.services import scenes

router = APIRouter(tags=["interior-materials"])


class InteriorMaterialOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    name_ru: str
    tabs: list[Literal["wall", "floor", "furniture", "tile"]]
    kind: Literal["paint", "wallpaper", "plaster", "wood", "stone", "tile"]
    base_color: str
    gloss_pct: int
    roughness: float
    texture_sha256: str | None
    texture_tile_size_mm: float | None
    texture_url: str | None


class InteriorMaterialAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    catalog_material_id: str | None = Field(default=None, max_length=120)
    label: str | None = Field(default=None, max_length=200)


def catalogue_out() -> list[InteriorMaterialOut]:
    return [
        InteriorMaterialOut(
            id=item.id,
            name=item.name,
            name_ru=item.name_ru,
            tabs=list(item.tabs),
            kind=item.kind,
            base_color=item.base_color,
            gloss_pct=item.gloss_pct,
            roughness=item.roughness,
            texture_sha256=item.texture_sha256,
            texture_tile_size_mm=item.texture_tile_size_mm,
            texture_url=(
                f"/api/v1/interior-materials/textures/{item.texture_sha256}.png"
                if item.texture_sha256
                else None
            ),
        )
        for item in all_materials()
    ]


@router.get("/interior-materials", response_model=list[InteriorMaterialOut])
def list_interior_materials() -> list[InteriorMaterialOut]:
    return catalogue_out()


@router.get("/interior-materials/textures/{sha256}.png", name="interior_material_texture")
def get_interior_material_texture(sha256: str) -> Response:
    data = texture_bytes(sha256)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": sha256},
    )


@router.post(
    "/models/{version_id}/interior-material",
    status_code=status.HTTP_201_CREATED,
    response_model=scene_api.SceneOut,
)
def assign_interior_material(
    version_id: uuid.UUID,
    body: InteriorMaterialAssign,
    db: DbDep,
    principal: PrincipalDep,
) -> scene_api.SceneOut:
    if body.catalog_material_id is not None:
        material_by_id(body.catalog_material_id)
    made = scenes.assign_interior_material(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        node_id=body.scene_node_id,
        material_id=body.catalog_material_id,
        label=body.label,
    )
    return scene_api.out_scene(db, made.id, principal)
