"""Direct mesh editing and surface details (T-235 / T-236, F-086).

The API side checks that the version can be edited as a mesh and enqueues; the worker does the
editing. A parametric version — one built from operations or imported as CAD — keeps its exact
B-Rep unless the caller explicitly asks to convert it to a mesh, so a click never silently
degrades a model the kernel can still change exactly.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session
from worker import meshedit

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job, Operation
from app.services import jobs, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

MESH_EDIT_JOB = "mesh_edit"
EDITABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})


def is_parametric(db: Session, version_id: uuid.UUID) -> bool:
    """True when the version carries a kernel operation history (an exact B-Rep)."""
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(Operation)
            .where(Operation.project_version_id == version_id)
        )
        or 0
    ) > 0


def validate_request(request: dict[str, Any]) -> meshedit.EditRequest:
    try:
        return meshedit.EditRequest.model_validate(request)
    except ValidationError as exc:
        problems = [
            {"where": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()[:8]
        ]
        raise ValidationFailedError("the edit request is not valid", {"errors": problems}) from None


def enqueue_mesh_edit(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    request: dict[str, Any],
    label: str | None = None,
    convert_to_mesh: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)

    spec = validate_request(request)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in EDITABLE_FORMATS:
        raise ValidationFailedError(
            "this version has no mesh to edit", {"editable_formats": sorted(EDITABLE_FORMATS)}
        )
    # A preview changes nothing, so it never needs the conversion consent.
    if not spec.preview and not convert_to_mesh and is_parametric(db, version.id):
        raise ValidationFailedError(
            "this version is parametric; editing its mesh turns it into a plain mesh. "
            "Edit it with operations to keep it exact, or repeat with convert_to_mesh=true",
            {"parametric": True},
        )

    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=MESH_EDIT_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "request": spec.model_dump(mode="json"),
            "label": label,
            "converted_from_parametric": bool(not spec.preview and convert_to_mesh),
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
