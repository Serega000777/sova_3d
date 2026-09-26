"""Organic shapes from a description (F-001/F-075).

The kernel builds what has dimensions; a figurine, an animal or a vase has none, so it is
generated as a mesh by a learned model instead. The result is a new version like any
import — honest about being a guess at a shape, then repaired and checked like any mesh.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.authz import require_workspace_role

GENERATE_MESH_JOB = "generate_mesh"


class MeshGenerationNotEnabledError(APIError):
    status_code = 501
    code = "mesh_generation_not_enabled"


def start_generation(
    db: Session,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    size_mm: float,
    idempotency_key: str | None = None,
) -> Job:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if settings.mesh_generation_provider == "none":
        raise MeshGenerationNotEnabledError(
            "shape generation from a description is not enabled on this server",
            {"setting": "MESH_GENERATION_PROVIDER"},
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=GENERATE_MESH_JOB,
        input={
            "project_id": str(project.id),
            "prompt": prompt,
            "size_mm": size_mm,
            "provider": settings.mesh_generation_provider,
        },
        created_by=user_id,
        project_id=project.id,
        idempotency_key=idempotency_key,
    )
