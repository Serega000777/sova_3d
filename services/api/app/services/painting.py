"""Paint requests (T-108, F-034): colour a version's model without changing its shape."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import ProjectVersion
from app.services import jobs, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

PAINT_JOB = "paint_model"
PAINTABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})
MAX_STROKES = 512


def inherited_paint(version: ProjectVersion) -> tuple[list[dict[str, Any]], str | None]:
    """The strokes a version carries, so new paint goes on top of them.

    The painted mesh is a preview; the strokes in `provenance["paint"]` are the source of
    truth — written by the paint job and carried across geometry edits (T-115) — and are
    replayed from the plain model, which keeps the subdivision from compounding.
    """
    carried = (version.provenance or {}).get("paint") or {}
    strokes = carried.get("strokes") or []
    base = carried.get("base_colour")
    return list(strokes), str(base) if base else None


def enqueue_paint(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    strokes: list[dict[str, Any]],
    base_colour: str | None = None,
    label: str | None = None,
    replace: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)

    asset = model_asset_of(db, version)
    if asset is None or asset.format not in PAINTABLE_FORMATS:
        raise ValidationFailedError(
            "this version has no mesh to paint",
            {"paintable_formats": sorted(PAINTABLE_FORMATS)},
        )
    if not strokes and not base_colour:
        raise ValidationFailedError("nothing to paint: give a stroke or a base colour")

    if not replace:
        earlier, earlier_base = inherited_paint(version)
        strokes = [*earlier, *strokes]
        base_colour = base_colour or earlier_base
    if len(strokes) > MAX_STROKES:
        raise ValidationFailedError(
            f"too many strokes ({len(strokes)} > {MAX_STROKES}); "
            "paint with replace=true to start from the bare model",
            {"strokes": len(strokes), "max": MAX_STROKES},
        )

    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=PAINT_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "strokes": strokes,
            "base_colour": base_colour,
            "label": label,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
