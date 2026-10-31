"""Safe Blender handoff: a fixed worker operation produces an editable ``.blend`` export."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.models.versioning import VersionState
from app.services import jobs, projects, scenes
from app.services.assets import model_asset_of, preview_asset_of
from app.services.authz import require_workspace_role

router = APIRouter(tags=["blender-handoffs"])


class BlenderHandoffCreate(BaseModel):
    """The only supported operation; no Python, add-ons, paths, or Blender arguments."""

    operation: Literal["editable_scene"] = "editable_scene"

    model_config = ConfigDict(extra="forbid", strict=True)


@router.post(
    "/models/{version_id}/blender-handoffs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_blender_handoff(
    version_id: uuid.UUID,
    body: BlenderHandoffCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    if version.state is not VersionState.finalized:
        raise ValidationFailedError("Blender handoff requires a finalized immutable version")
    provenance = version.provenance or {}
    has_scene = "scene" in provenance
    if has_scene and not scenes.has_explicit_scene(version):
        raise ValidationFailedError("the scene schema is not supported for Blender handoff")
    if has_scene:
        resolved = scenes.resolve_scene(
            db,
            version=version,
            workspace_id=project.workspace_id,
        )
        if not any(node["kind"] == "object" and node["effective_visible"] for node in resolved):
            raise ValidationFailedError("the scene has no visible geometry for Blender handoff")
    else:
        source = preview_asset_of(db, version) or model_asset_of(db, version)
        if source is None or source.format is None:
            raise ValidationFailedError("version has no model asset for Blender handoff")

    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type="blender_handoff",
        input={
            "version_id": str(version.id),
            "contract_version": 1,
            "operation": body.operation,
        },
        created_by=principal.user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
        max_attempts=1,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
