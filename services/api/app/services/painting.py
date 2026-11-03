"""Paint requests (T-108, F-034): colour a version's model without changing its shape."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Sequence
from itertools import product
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.geometry.region import Axis, BoxRegion, LassoRegion, Region
from app.interior_materials import material_by_id, texture_bytes
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import Asset, ProjectVersion
from app.services import jobs, projects, scenes
from app.services.assets import model_asset_of
from app.services.authz import require_workspace_role

PAINT_JOB = "paint_model"
PAINTABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})
MAX_STROKES = 512
REGION_ADAPTER: TypeAdapter[Region] = TypeAdapter(Region)


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


def inherited_paint(
    version: ProjectVersion, *, scene_node_id: str | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """The strokes a version carries, so new paint goes on top of them.

    The painted mesh is a preview; the strokes in `provenance["paint"]` are the source of
    truth — written by the paint job and carried across geometry edits (T-115) — and are
    replayed from the plain model, which keeps the subdivision from compounding.
    """
    if scene_node_id is None:
        carried = (version.provenance or {}).get("paint") or {}
    else:
        by_node = (version.provenance or {}).get("scene_paint") or {}
        carried = by_node.get(scene_node_id) if isinstance(by_node, dict) else {}
        carried = carried if isinstance(carried, dict) else {}
    strokes = carried.get("strokes") or []
    base = carried.get("base_colour")
    return list(strokes), str(base) if base else None


def inherited_layers(
    version: ProjectVersion, *, scene_node_id: str | None = None
) -> list[dict[str, Any]]:
    if scene_node_id is None:
        carried = (version.provenance or {}).get("paint") or {}
    else:
        by_node = (version.provenance or {}).get("scene_paint") or {}
        carried = by_node.get(scene_node_id) if isinstance(by_node, dict) else {}
        carried = carried if isinstance(carried, dict) else {}
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


def scene_source(
    db: Session,
    *,
    version: ProjectVersion,
    workspace_id: uuid.UUID,
    scene_node_id: str,
) -> tuple[Asset, dict[str, Any]]:
    """Resolve one visible direct object and its trusted bare paint source.

    Current paint regions are axis-aligned boxes/lassos. Only a proper signed axis permutation
    (90-degree rotations or reflections, optional scale and translation) keeps that
    representation exact in object-local millimetres. Arbitrary rotation and shear fail closed.
    """

    target = scenes.direct_object(
        db,
        version=version,
        workspace_id=workspace_id,
        node_id=scene_node_id,
    )
    if not target.get("effective_visible"):
        raise ValidationFailedError(
            "a hidden scene object cannot be painted", {"scene_node_id": scene_node_id}
        )
    _axis_mapping(target["world_transform"], scene_node_id=scene_node_id)

    current_asset_id = uuid.UUID(str(target["resolved_asset_id"]))
    source_asset_id = current_asset_id
    by_node = (version.provenance or {}).get("scene_paint")
    record = by_node.get(scene_node_id) if isinstance(by_node, dict) else None
    if (
        isinstance(record, dict)
        and record.get("painted_asset_id") == str(current_asset_id)
        and isinstance(record.get("source_asset_id"), str)
    ):
        try:
            source_asset_id = uuid.UUID(record["source_asset_id"])
        except ValueError as exc:
            raise ValidationFailedError(
                "stored scene paint source is malformed", {"scene_node_id": scene_node_id}
            ) from exc
    source = db.get(Asset, source_asset_id)
    if source is None or source.workspace_id != workspace_id:
        raise ValidationFailedError(
            "stored scene paint source is unavailable", {"scene_node_id": scene_node_id}
        )
    if source.format not in PAINTABLE_FORMATS:
        raise ValidationFailedError(
            "this scene object has no paintable mesh",
            {"scene_node_id": scene_node_id, "paintable_formats": sorted(PAINTABLE_FORMATS)},
        )
    return source, target


def _axis_mapping(
    world_transform: list[list[float]], *, scene_node_id: str
) -> tuple[list[int], list[float]]:
    """Map each world axis to exactly one local axis, including exact reflections."""

    mapping: list[int] = []
    coefficients: list[float] = []
    used: set[int] = set()
    for row in range(3):
        nonzero = [column for column in range(3) if abs(float(world_transform[row][column])) > 1e-7]
        if len(nonzero) != 1 or nonzero[0] in used:
            raise ValidationFailedError(
                "scene painting requires a signed axis permutation "
                "without arbitrary rotation or shear",
                {"scene_node_id": scene_node_id},
            )
        column = nonzero[0]
        mapping.append(column)
        coefficients.append(float(world_transform[row][column]))
        used.add(column)
    linear = [row[:3] for row in world_transform[:3]]
    determinant = (
        linear[0][0] * (linear[1][1] * linear[2][2] - linear[1][2] * linear[2][1])
        - linear[0][1] * (linear[1][0] * linear[2][2] - linear[1][2] * linear[2][0])
        + linear[0][2] * (linear[1][0] * linear[2][1] - linear[1][1] * linear[2][0])
    )
    if abs(determinant) <= 1e-12:
        raise ValidationFailedError(
            "scene painting requires a non-collapsed signed axis permutation",
            {"scene_node_id": scene_node_id},
        )
    return mapping, coefficients


def _region_in_object_space(
    region_payload: object, world_transform: list[list[float]], *, scene_node_id: str
) -> dict[str, Any]:
    try:
        region = REGION_ADAPTER.validate_python(region_payload)
    except ValidationError as exc:
        raise ValidationFailedError(
            "paint region is malformed", {"scene_node_id": scene_node_id}
        ) from exc
    translation = [float(world_transform[index][3]) for index in range(3)]
    mapping, coefficients = _axis_mapping(world_transform, scene_node_id=scene_node_id)

    def local_point(world: Sequence[float]) -> list[float]:
        local = [0.0, 0.0, 0.0]
        for world_axis in range(3):
            local[mapping[world_axis]] = (
                float(world[world_axis]) - translation[world_axis]
            ) / coefficients[world_axis]
        return local

    if isinstance(region, BoxRegion):
        corners = [
            local_point(corner)
            for corner in product(*zip(region.min_mm, region.max_mm, strict=True))
        ]
        return BoxRegion(
            min_mm=(
                min(corner[0] for corner in corners),
                min(corner[1] for corner in corners),
                min(corner[2] for corner in corners),
            ),
            max_mm=(
                max(corner[0] for corner in corners),
                max(corner[1] for corner in corners),
                max(corner[2] for corner in corners),
            ),
        ).model_dump(mode="json")
    world_axis = "xyz".index(region.axis)
    local_axis = mapping[world_axis]
    world_plane = [index for index in range(3) if index != world_axis]
    local_plane = [index for index in range(3) if index != local_axis]
    axes: list[Axis] = ["x", "y", "z"]
    local_points: list[tuple[float, float]] = []
    for point in region.points_mm:
        world = [0.0, 0.0, 0.0]
        world[world_axis] = region.offset_mm
        world[world_plane[0]], world[world_plane[1]] = point
        local = local_point(world)
        local_points.append((local[local_plane[0]], local[local_plane[1]]))
    return LassoRegion(
        axis=axes[local_axis],
        offset_mm=(region.offset_mm - translation[world_axis]) / coefficients[world_axis],
        depth_mm=region.depth_mm / abs(coefficients[world_axis]),
        points_mm=local_points,
    ).model_dump(mode="json")


def _local_strokes(
    strokes: list[dict[str, Any]], target: dict[str, Any], *, scene_node_id: str
) -> list[dict[str, Any]]:
    localized: list[dict[str, Any]] = []
    for stroke in strokes:
        item = dict(stroke)
        if "region" in item:
            item["region"] = _region_in_object_space(
                item["region"], target["world_transform"], scene_node_id=scene_node_id
            )
        localized.append(item)
    return localized


def reorder_layers(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    layer_order: list[str],
    scene_node_id: str | None = None,
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

    if scenes.has_explicit_scene(version):
        if scene_node_id is None:
            raise ValidationFailedError(
                "a multi-object scene paint request must name scene_node_id"
            )
        asset, _ = scene_source(
            db,
            version=version,
            workspace_id=project.workspace_id,
            scene_node_id=scene_node_id,
        )
    else:
        if scene_node_id is not None:
            raise ValidationFailedError("scene_node_id is only valid for a multi-object scene")
        legacy_asset = model_asset_of(db, version)
        if legacy_asset is None or legacy_asset.format not in PAINTABLE_FORMATS:
            raise ValidationFailedError(
                "this version has no mesh to paint",
                {"paintable_formats": sorted(PAINTABLE_FORMATS)},
            )
        asset = legacy_asset

    strokes, base_colour = inherited_paint(version, scene_node_id=scene_node_id)
    layers = inherited_layers(version, scene_node_id=scene_node_id)
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
            "scene_node_id": scene_node_id,
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
    scene_node_id: str | None = None,
    replace: bool = False,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)

    if scenes.has_explicit_scene(version):
        if scene_node_id is None:
            raise ValidationFailedError(
                "a multi-object scene paint request must name scene_node_id"
            )
        asset, target = scene_source(
            db,
            version=version,
            workspace_id=project.workspace_id,
            scene_node_id=scene_node_id,
        )
        strokes = _local_strokes(strokes, target, scene_node_id=scene_node_id)
    else:
        if scene_node_id is not None:
            raise ValidationFailedError("scene_node_id is only valid for a multi-object scene")
        legacy_asset = model_asset_of(db, version)
        if legacy_asset is None or legacy_asset.format not in PAINTABLE_FORMATS:
            raise ValidationFailedError(
                "this version has no mesh to paint",
                {"paintable_formats": sorted(PAINTABLE_FORMATS)},
            )
        asset = legacy_asset
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
        earlier, earlier_base = inherited_paint(version, scene_node_id=scene_node_id)
        layers = inherited_layers(version, scene_node_id=scene_node_id)
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
            "scene_node_id": scene_node_id,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
