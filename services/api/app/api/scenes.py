"""Multi-object scene hierarchy endpoints (T-241)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.interior_materials import material_by_id
from app.services import assembly_inspection, projects, scenes

router = APIRouter(tags=["scenes"])

MatrixRow = Annotated[list[float], Field(min_length=4, max_length=4)]
Matrix4 = Annotated[list[MatrixRow], Field(min_length=4, max_length=4)]
Footprint = Annotated[list[float], Field(min_length=2, max_length=2)]


class SceneAppearanceOut(BaseModel):
    schema_version: Literal[1]
    catalog_material_id: str
    name: str
    name_ru: str
    base_color: str
    gloss_pct: int
    roughness: float
    texture_sha256: str | None
    texture_tile_size_mm: float | None
    texture_url: str | None


class SceneNode(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["group", "object"]
    parent_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    visible: bool = True
    transform: Matrix4 = Field(default_factory=lambda: [row[:] for row in scenes.IDENTITY])
    asset_id: uuid.UUID | None = None
    instance_of: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    # A declared [width_mm, depth_mm] 2D footprint for the plan-view furniture overlay. An
    # object's own placement job sets this once; it is not derived from the mesh so a later
    # rename never loses it. Deep validation (positive, bounded, object-only) lives in
    # app.services.scenes so every entry path — this API and job-created nodes alike — is
    # fail-closed the same way `transform` already is.
    footprint_mm: Footprint | None = None
    # Present only so an exact GET response can be round-tripped for rename/reparent edits.
    # The service compares it to the current immutable snapshot and rejects any forged value.
    appearance: SceneAppearanceOut | None = Field(
        default=None, json_schema_extra={"readOnly": True}
    )


class SceneNodeOut(SceneNode):
    resolved_asset_id: uuid.UUID | None
    format: str | None
    world_transform: Matrix4
    effective_visible: bool
    appearance: SceneAppearanceOut | None = None


class SceneOut(BaseModel):
    version_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    nodes: list[SceneNodeOut]


class AssemblyComponentOut(BaseModel):
    order: int
    node_id: str
    source_node_id: str
    name: str
    parent_id: str | None
    instance_of: str | None
    resolved_asset_id: uuid.UUID
    effective_visible: bool
    world_transform: Matrix4


class AssemblyBomItemOut(BaseModel):
    source_node_id: str
    name: str
    resolved_asset_id: uuid.UUID
    quantity: int
    visible_quantity: int
    node_ids: list[str]


class AssemblyInspectionOut(BaseModel):
    version_id: uuid.UUID
    component_count: int
    visible_component_count: int
    unique_geometry_count: int
    components: list[AssemblyComponentOut]
    bom: list[AssemblyBomItemOut]
    exploded_order: list[str]
    structure_validated: Literal[True] = True
    constraints_status: Literal["not_modeled"] = "not_modeled"
    collision_status: Literal["not_checked"] = "not_checked"
    limitations: list[str]


class SceneEdit(BaseModel):
    nodes: list[SceneNode] = Field(min_length=1, max_length=scenes.MAX_SCENE_NODES)
    label: str | None = Field(default=None, max_length=200)


def _appearance_out(value: dict[str, object] | None) -> SceneAppearanceOut | None:
    if value is None:
        return None
    material = material_by_id(str(value["catalog_material_id"]))
    texture_sha256 = value.get("texture_sha256")
    return SceneAppearanceOut.model_validate(
        {
            **value,
            "name": material.name,
            "name_ru": material.name_ru,
            "texture_url": (
                f"/api/v1/interior-materials/textures/{texture_sha256}.png"
                if texture_sha256
                else None
            ),
        }
    )


def out_scene(db: DbDep, version_id: uuid.UUID, principal: PrincipalDep) -> SceneOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    nodes = scenes.resolve_scene(db, version=version, workspace_id=project.workspace_id)
    return SceneOut(
        version_id=version.id,
        parent_version_id=version.parent_version_id,
        nodes=[
            SceneNodeOut.model_validate(
                {**node, "appearance": _appearance_out(node.get("appearance"))}
            )
            for node in nodes
        ],
    )


@router.get("/models/{version_id}/scene", response_model=SceneOut)
def get_scene(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> SceneOut:
    return out_scene(db, version_id, principal)


@router.get(
    "/models/{version_id}/assembly-inspection",
    response_model=AssemblyInspectionOut,
)
def inspect_assembly(
    version_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> AssemblyInspectionOut:
    """Return an exact component order and instance-aware BOM for one validated scene.

    Fetching the scene already validates hierarchy, assets and affine world transforms. This
    endpoint deliberately does not infer mates, joints or contact from those transforms.
    """
    scene = out_scene(db, version_id, principal)
    objects = [node for node in scene.nodes if node.kind == "object"]
    components = [
        AssemblyComponentOut(
            order=index,
            node_id=node.id,
            source_node_id=node.instance_of or node.id,
            name=node.name,
            parent_id=node.parent_id,
            instance_of=node.instance_of,
            resolved_asset_id=node.resolved_asset_id,
            effective_visible=node.effective_visible,
            world_transform=node.world_transform,
        )
        for index, node in enumerate(objects, start=1)
        if node.resolved_asset_id is not None
    ]
    by_source: dict[str, list[AssemblyComponentOut]] = {}
    for component in components:
        by_source.setdefault(component.source_node_id, []).append(component)
    component_by_id = {component.node_id: component for component in components}
    bom = [
        AssemblyBomItemOut(
            source_node_id=source_id,
            name=component_by_id[source_id].name,
            resolved_asset_id=component_by_id[source_id].resolved_asset_id,
            quantity=len(items),
            visible_quantity=sum(item.effective_visible for item in items),
            node_ids=[item.node_id for item in items],
        )
        for source_id, items in by_source.items()
    ]
    return AssemblyInspectionOut(
        version_id=scene.version_id,
        component_count=len(components),
        visible_component_count=sum(item.effective_visible for item in components),
        unique_geometry_count=len({item.resolved_asset_id for item in components}),
        components=components,
        bom=bom,
        exploded_order=[item.node_id for item in components if item.effective_visible],
        limitations=[
            "exploded order follows the immutable scene node order; it is not an assembly sequence",
            "mate and joint constraints are not modeled",
            "whole-scene transformed collision and contact are not checked",
        ],
    )


@router.post(
    "/models/{version_id}/assembly-inspection",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def start_assembly_geometry_inspection(
    version_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    """Measure transformed world envelopes without claiming collision/contact or physics."""
    job = assembly_inspection.enqueue(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/scene",
    status_code=status.HTTP_201_CREATED,
    response_model=SceneOut,
)
def edit_scene(
    version_id: uuid.UUID, body: SceneEdit, db: DbDep, principal: PrincipalDep
) -> SceneOut:
    nodes: list[dict[str, Any]] = []
    for node in body.nodes:
        value = node.model_dump(mode="json")
        if "appearance" not in node.model_fields_set:
            value.pop("appearance", None)
        nodes.append(value)
    made = scenes.create_scene_version(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        nodes=nodes,
        label=body.label,
    )
    return out_scene(db, made.id, principal)
