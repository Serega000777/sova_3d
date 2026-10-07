"""Mesh editing endpoints (T-235 / T-236, F-086): edit components, add surface details."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from worker import meshedit

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.services import entitlements, mesh_edit, projects, scenes

router = APIRouter(tags=["mesh-edit"])


class MeshEditBody(BaseModel):
    """Operations run in order on the version's mesh. Selections carry millimetre coordinates
    (one point per vertex, two per edge, three per face), not indices; the operation shapes are
    the worker's `EditRequest` and are checked before anything is queued."""

    operations: list[meshedit.Operation] = Field(min_length=1, max_length=32)
    # Only check and report (footprint, triangle estimate); create no version.
    preview: bool = False
    # How many triangles the selection was made on; a changed mesh is refused as stale.
    expected_faces: int | None = Field(default=None, ge=1)
    # Features below this size are refused instead of producing slivers.
    tolerance_mm: float = Field(default=0.2, gt=0.0, le=5.0)
    label: str | None = Field(default=None, max_length=200)
    # Required to edit a parametric version's mesh; it becomes a plain mesh version.
    convert_to_mesh: bool = False
    # Required for an explicit multi-object scene. Coordinates are world-space; the API
    # converts them through this direct geometry node's rigid transform.
    scene_node_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class MeshModifierStackItem(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    enabled: bool = True


class MeshModifierStackItemOut(MeshModifierStackItem):
    sequence_no: int
    type: str
    params: dict[str, Any]
    tolerance_mm: float


class MeshModifierStackOut(BaseModel):
    version_id: uuid.UUID
    scene_node_id: str | None
    base_version_id: uuid.UUID
    base_asset_id: uuid.UUID
    modifiers: list[MeshModifierStackItemOut]


class MeshModifierStackEdit(BaseModel):
    modifiers: list[MeshModifierStackItem] = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=200)
    scene_node_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")


@router.get("/models/{version_id}/mesh-modifier-stack", response_model=MeshModifierStackOut)
def get_mesh_modifier_stack(
    version_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    scene_node_id: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{0,63}$")] = None,
) -> MeshModifierStackOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    if scenes.has_explicit_scene(version):
        if scene_node_id is None:
            raise ValidationFailedError("a multi-object scene stack must name scene_node_id")
        scenes.editable_object(
            db,
            version=version,
            workspace_id=project.workspace_id,
            node_id=scene_node_id,
        )
    elif scene_node_id is not None:
        raise ValidationFailedError(
            "scene_node_id is only valid for an explicit multi-object scene",
            {"scene_node_id": scene_node_id},
        )
    stack = mesh_edit.modifier_stack(db, version.id, scene_node_id=scene_node_id)
    if not stack:
        raise ValidationFailedError(
            "this version has no mesh modifier history to edit",
            {"version_id": str(version.id)},
        )
    base_version_id, base_asset = mesh_edit.modifier_stack_base(
        db,
        version,
        workspace_id=project.workspace_id,
        scene_node_id=scene_node_id,
    )
    return MeshModifierStackOut(
        version_id=version.id,
        scene_node_id=scene_node_id,
        base_version_id=base_version_id,
        base_asset_id=base_asset.id,
        modifiers=[
            MeshModifierStackItemOut(
                id=item.key,
                enabled=item.enabled,
                sequence_no=index,
                type=str(item.operation["op"]),
                params=item.operation,
                tolerance_mm=item.tolerance_mm,
            )
            for index, item in enumerate(stack, start=1)
        ],
    )


@router.post(
    "/models/{version_id}/mesh-modifier-stack",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def edit_mesh_modifier_stack(
    version_id: uuid.UUID,
    body: MeshModifierStackEdit,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    entitlements.require(db, principal.user_id, entitlements.Capability.mesh_edit)
    job = mesh_edit.enqueue_modifier_stack_edit(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        items=[item.model_dump(mode="json") for item in body.modifiers],
        label=body.label,
        scene_node_id=body.scene_node_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/mesh-edit",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def edit_mesh(
    version_id: uuid.UUID,
    body: MeshEditBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    entitlements.require(db, principal.user_id, entitlements.Capability.mesh_edit)
    request: dict[str, Any] = {
        "operations": [op.model_dump(mode="json") for op in body.operations],
        "preview": body.preview,
        "tolerance_mm": body.tolerance_mm,
    }
    if body.expected_faces is not None:
        request["expected_faces"] = body.expected_faces
    job = mesh_edit.enqueue_mesh_edit(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        request=request,
        label=body.label,
        convert_to_mesh=body.convert_to_mesh,
        scene_node_id=body.scene_node_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
