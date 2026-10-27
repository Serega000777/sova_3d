"""Queue bounded geometry-envelope inspection for one immutable scene."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import Asset
from app.services import jobs, projects, scenes
from app.services.authz import require_workspace_role

ASSEMBLY_INSPECTION_JOB = "inspect_assembly_geometry"
MAX_INSPECTION_COMPONENTS = 64
SUPPORTED_FORMATS = frozenset({"stl", "glb"})


def enqueue(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.viewer)
    resolved = scenes.resolve_scene(db, version=version, workspace_id=project.workspace_id)
    components: list[dict[str, object]] = []
    for node in resolved:
        if node["kind"] != "object" or not node["effective_visible"]:
            continue
        asset_id = node.get("resolved_asset_id")
        asset = db.get(Asset, asset_id) if asset_id is not None else None
        if asset is None or asset.format not in SUPPORTED_FORMATS:
            raise ValidationFailedError(
                "every visible assembly component needs a measurable STL or GLB mesh",
                {"node_id": node["id"], "format": asset.format if asset else None},
            )
        components.append(
            {
                "node_id": node["id"],
                "asset_id": str(asset.id),
                "format": asset.format,
                "world_transform": node["world_transform"],
            }
        )
    if not components:
        raise ValidationFailedError("the assembly has no visible geometry components")
    if len(components) > MAX_INSPECTION_COMPONENTS:
        raise ValidationFailedError(
            "the assembly has too many visible components for one bounded inspection",
            {"maximum": MAX_INSPECTION_COMPONENTS},
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=ASSEMBLY_INSPECTION_JOB,
        input={"version_id": str(version.id), "components": components},
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
