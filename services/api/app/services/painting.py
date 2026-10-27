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


def inherited_layers(version: ProjectVersion) -> list[dict[str, Any]]:
    carried = (version.provenance or {}).get("paint") or {}
    layers = carried.get("layers") or []
    stroke_count = len(carried.get("strokes") or [])
    trusted: list[dict[str, Any]] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = layer.get("name")
        start = layer.get("stroke_start")
        count = layer.get("stroke_count")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or start < 0
            or count < 1
            or start + count > stroke_count
        ):
            continue
        trusted.append({"name": name, "stroke_start": start, "stroke_count": count})
    return trusted


def enqueue_paint(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    strokes: list[dict[str, Any]],
    base_colour: str | None = None,
    label: str | None = None,
    layer_name: str | None = None,
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
    new_stroke_count = len(strokes)
    if not strokes and not base_colour:
        raise ValidationFailedError("nothing to paint: give a stroke or a base colour")
    if layer_name and not strokes:
        raise ValidationFailedError("a named paint layer needs at least one stroke")

    layers: list[dict[str, Any]] = []
    if not replace:
        earlier, earlier_base = inherited_paint(version)
        layers = inherited_layers(version)
        strokes = [*earlier, *strokes]
        base_colour = base_colour or earlier_base
    if layer_name:
        layers.append(
            {
                "name": layer_name,
                "stroke_start": len(strokes) - new_stroke_count,
                "stroke_count": new_stroke_count,
            }
        )
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
            "layers": layers,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
