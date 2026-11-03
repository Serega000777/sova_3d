"""Paint requests (T-108, F-034): colour a version's model without changing its shape."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.interior_materials import material_by_id, texture_bytes
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import ProjectVersion
from app.services import jobs, projects
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

PAINT_JOB = "paint_model"
PAINTABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})
MAX_STROKES = 512


def worker_strokes(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand catalogue ids into trusted worker snapshots and content-addressed bytes."""
    trusted: list[dict[str, Any]] = []
    for stroke in strokes:
        unexpected = set(stroke) - {"colour", "catalog_material_id", "opacity", "region"}
        if unexpected:
            raise ValidationFailedError(
                "paint stroke contains unsupported fields", {"fields": sorted(unexpected)}
            )
        material_id = stroke.get("catalog_material_id")
        if material_id is None:
            trusted.append(dict(stroke))
            continue
        if not isinstance(material_id, str):
            raise ValidationFailedError("paint material id must be a string")
        material = material_by_id(material_id)
        resolved: dict[str, Any] = {
            "catalog_material_id": material.id,
            "base_color": material.base_color,
            "roughness": material.roughness,
            "metallic": material.metallic,
            "texture_sha256": material.texture_sha256,
            "texture_tile_size_mm": material.texture_tile_size_mm,
            "texture_data_b64": (
                base64.b64encode(texture_bytes(material.texture_sha256)).decode("ascii")
                if material.texture_sha256
                else None
            ),
        }
        trusted.append(
            {
                **{key: value for key, value in stroke.items() if key != "catalog_material_id"},
                "material": resolved,
            }
        )
    return trusted


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


def reorder_layers(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    layer_order: list[str],
    idempotency_key: str | None = None,
) -> Job:
    """Repaint with the same strokes replayed in a new layer order.

    Compositing is last-stroke-wins in stroke-array order, so changing which layer paints
    last changes the visible result at every face two layers both touch. This only accepts a
    version whose entire stroke history is already named: a gap or an overlapping range would
    make "where does the unnamed paint go" an unanswerable, invented choice.
    """
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)

    asset = model_asset_of(db, version)
    if asset is None or asset.format not in PAINTABLE_FORMATS:
        raise ValidationFailedError(
            "this version has no mesh to paint",
            {"paintable_formats": sorted(PAINTABLE_FORMATS)},
        )

    strokes, base_colour = inherited_paint(version)
    layers = inherited_layers(version)
    if not layers:
        raise ValidationFailedError("this version has no named paint layers to reorder")
    by_name: dict[str, dict[str, Any]] = {}
    for layer in layers:
        if layer["name"] in by_name:
            raise ValidationFailedError(
                "duplicate paint layer names cannot be reordered safely",
                {"name": layer["name"]},
            )
        by_name[layer["name"]] = layer
    if len(layer_order) != len(layers) or set(layer_order) != set(by_name):
        raise ValidationFailedError(
            "layer_order must be a permutation of every existing named layer",
            {"existing_layers": sorted(by_name), "given": layer_order},
        )
    for previous, current in zip(
        sorted(layers, key=lambda layer: layer["stroke_start"]),
        sorted(layers, key=lambda layer: layer["stroke_start"])[1:],
        strict=False,
    ):
        if previous["stroke_start"] + previous["stroke_count"] != current["stroke_start"]:
            raise ValidationFailedError(
                "every stroke must belong to exactly one named layer before reordering",
                {"gap_or_overlap_after": previous["name"]},
            )
    first = min(layers, key=lambda layer: layer["stroke_start"])
    last = max(layers, key=lambda layer: layer["stroke_start"] + layer["stroke_count"])
    if first["stroke_start"] != 0 or last["stroke_start"] + last["stroke_count"] != len(strokes):
        raise ValidationFailedError(
            "every stroke must belong to exactly one named layer before reordering"
        )

    new_strokes: list[dict[str, Any]] = []
    new_layers: list[dict[str, Any]] = []
    for name in layer_order:
        layer = by_name[name]
        segment = strokes[layer["stroke_start"] : layer["stroke_start"] + layer["stroke_count"]]
        new_layers.append(
            {"name": name, "stroke_start": len(new_strokes), "stroke_count": len(segment)}
        )
        new_strokes.extend(segment)

    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=PAINT_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "strokes": new_strokes,
            "base_colour": base_colour,
            "label": "Reorder paint layers",
            "layers": new_layers,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )


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
    for stroke in strokes:
        material_id = stroke.get("catalog_material_id")
        if material_id is not None:
            if not isinstance(material_id, str):
                raise ValidationFailedError("paint material id must be a string")
            material_by_id(material_id)
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
