"""Multi-object scene hierarchy endpoints (T-241)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.services import projects, scenes

router = APIRouter(tags=["scenes"])

MatrixRow = Annotated[list[float], Field(min_length=4, max_length=4)]
Matrix4 = Annotated[list[MatrixRow], Field(min_length=4, max_length=4)]


class SceneNode(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["group", "object"]
    parent_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    visible: bool = True
    transform: Matrix4 = Field(default_factory=lambda: [row[:] for row in scenes.IDENTITY])
    asset_id: uuid.UUID | None = None
    instance_of: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class SceneNodeOut(SceneNode):
    resolved_asset_id: uuid.UUID | None
    format: str | None
    world_transform: Matrix4
    effective_visible: bool


class SceneOut(BaseModel):
    version_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    nodes: list[SceneNodeOut]


class SceneEdit(BaseModel):
    nodes: list[SceneNode] = Field(min_length=1, max_length=scenes.MAX_SCENE_NODES)
    label: str | None = Field(default=None, max_length=200)


def _out(db: DbDep, version_id: uuid.UUID, principal: PrincipalDep) -> SceneOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    nodes = scenes.resolve_scene(db, version=version, workspace_id=project.workspace_id)
    return SceneOut(
        version_id=version.id,
        parent_version_id=version.parent_version_id,
        nodes=[SceneNodeOut.model_validate(node) for node in nodes],
    )


@router.get("/models/{version_id}/scene", response_model=SceneOut)
def get_scene(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> SceneOut:
    return _out(db, version_id, principal)


@router.post(
    "/models/{version_id}/scene",
    status_code=status.HTTP_201_CREATED,
    response_model=SceneOut,
)
def edit_scene(
    version_id: uuid.UUID, body: SceneEdit, db: DbDep, principal: PrincipalDep
) -> SceneOut:
    made = scenes.create_scene_version(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        nodes=[node.model_dump(mode="json") for node in body.nodes],
        label=body.label,
    )
    return _out(db, made.id, principal)
