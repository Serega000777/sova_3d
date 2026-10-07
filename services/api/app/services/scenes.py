"""Immutable multi-object scene graphs (T-241).

Scene rows live in a version's provenance because the complete graph is immutable with the
version. Geometry remains in the content-addressed Asset table: an instance points at a scene
node that owns one asset, so neither the database nor object storage duplicates its bytes.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import MeshModifier
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.services import projects
from app.services.authz import require_workspace_role

IDENTITY: list[list[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
SCENE_SCHEMA_VERSION = 1
MAX_SCENE_NODES = 256
# The web viewer loads these canonical single-file meshes directly. Import jobs normalize the
# wider accepted format catalogue to STL/GLB before a version can join a scene.
SCENE_FORMATS = frozenset({"stl", "glb"})


def _matrix(value: object, *, node_id: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValidationFailedError(
            "a scene transform must be a 4 by 4 matrix", {"node_id": node_id}
        )
    matrix: list[list[float]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 4:
            raise ValidationFailedError(
                "a scene transform must be a 4 by 4 matrix", {"node_id": node_id}
            )
        numbers = [float(item) for item in row]
        if any(not math.isfinite(item) or abs(item) > 1_000_000 for item in numbers):
            raise ValidationFailedError(
                "a scene transform contains a non-finite or out-of-range value",
                {"node_id": node_id},
            )
        matrix.append(numbers)
    if any(abs(matrix[3][index] - expected) > 1e-9 for index, expected in enumerate((0, 0, 0, 1))):
        raise ValidationFailedError("a scene transform must be affine", {"node_id": node_id})
    # A collapsed transform cannot be inverted for selection/export and is never useful.
    a, b, c = matrix[0][:3]
    d, e, f = matrix[1][:3]
    g, h, i = matrix[2][:3]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) < 1e-12:
        raise ValidationFailedError(
            "a scene transform cannot collapse geometry", {"node_id": node_id}
        )
    return matrix


def _multiply(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> list[list[float]]:
    return [
        [sum(left[row][step] * right[step][column] for step in range(4)) for column in range(4)]
        for row in range(4)
    ]


def _stored_nodes(version: ProjectVersion) -> list[dict[str, Any]]:
    scene = (version.provenance or {}).get("scene")
    if isinstance(scene, dict) and scene.get("schema_version") == SCENE_SCHEMA_VERSION:
        nodes = scene.get("nodes")
        if isinstance(nodes, list):
            return [dict(node) for node in nodes if isinstance(node, dict)]
    # Backward compatibility: a historical single-model version is a one-node scene.
    model_links = [link for link in version.assets if link.role is AssetRole.model]
    return [
        {
            "id": f"object_{index}",
            "name": f"Object {index}",
            "kind": "object",
            "parent_id": None,
            "visible": True,
            "transform": IDENTITY,
            "asset_id": str(link.asset_id),
            "instance_of": None,
        }
        for index, link in enumerate(model_links, start=1)
    ]


def has_explicit_scene(version: ProjectVersion) -> bool:
    scene = (version.provenance or {}).get("scene")
    return isinstance(scene, dict) and scene.get("schema_version") == SCENE_SCHEMA_VERSION


def stored_nodes(version: ProjectVersion) -> list[dict[str, Any]]:
    """Return a detached copy suitable for one immutable scene mutation."""
    return _stored_nodes(version)


def resolve_scene(
    db: Session,
    *,
    version: ProjectVersion,
    workspace_id: uuid.UUID,
    nodes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Validate and resolve a complete graph, including world transforms and instance assets."""
    raw = nodes if nodes is not None else _stored_nodes(version)
    if not raw:
        return []
    if len(raw) > MAX_SCENE_NODES:
        raise ValidationFailedError("a scene has too many nodes", {"maximum": MAX_SCENE_NODES})
    ids = [str(item.get("id", "")) for item in raw]
    if len(set(ids)) != len(ids):
        raise ValidationFailedError("every scene node id must appear exactly once")
    by_id = {str(item["id"]): dict(item) for item in raw}
    assets: dict[uuid.UUID, Asset] = {}
    for node_id, node in by_id.items():
        kind = node.get("kind")
        parent_id = node.get("parent_id")
        asset_id = node.get("asset_id")
        instance_of = node.get("instance_of")
        node["transform"] = _matrix(node.get("transform", IDENTITY), node_id=node_id)
        if parent_id is not None and str(parent_id) not in by_id:
            raise ValidationFailedError(
                "a scene node names a missing parent", {"node_id": node_id, "parent_id": parent_id}
            )
        if parent_id == node_id:
            raise ValidationFailedError("a scene node cannot parent itself", {"node_id": node_id})
        if kind == "group":
            if asset_id is not None or instance_of is not None:
                raise ValidationFailedError(
                    "a group cannot own geometry or be an instance", {"node_id": node_id}
                )
            continue
        if kind != "object":
            raise ValidationFailedError("a scene node kind is not supported", {"node_id": node_id})
        if (asset_id is None) == (instance_of is None):
            raise ValidationFailedError(
                "an object must own one asset or reference one instance target",
                {"node_id": node_id},
            )
        if asset_id is not None:
            try:
                parsed = uuid.UUID(str(asset_id))
            except ValueError as exc:
                raise ValidationFailedError(
                    "a scene asset id is invalid", {"node_id": node_id}
                ) from exc
            asset = db.get(Asset, parsed)
            if asset is None or asset.workspace_id != workspace_id:
                raise NotFoundError("asset", parsed)
            if asset.format not in SCENE_FORMATS:
                raise ValidationFailedError(
                    "a scene object needs a supported mesh asset",
                    {"node_id": node_id, "format": asset.format},
                )
            assets[parsed] = asset

    # Parent cycles are independent from instance references and get a precise error.
    states: dict[str, int] = {}

    def visit(node_id: str) -> None:
        state = states.get(node_id, 0)
        if state == 1:
            raise ValidationFailedError(
                "the scene hierarchy contains a cycle", {"node_id": node_id}
            )
        if state == 2:
            return
        states[node_id] = 1
        parent_id = by_id[node_id].get("parent_id")
        if parent_id is not None:
            visit(str(parent_id))
        states[node_id] = 2

    for node_id in by_id:
        visit(node_id)

    for node_id, node in by_id.items():
        target_id = node.get("instance_of")
        if target_id is None:
            continue
        target = by_id.get(str(target_id))
        if (
            target is None
            or target.get("kind") != "object"
            or target.get("asset_id") is None
            or target.get("instance_of") is not None
            or str(target_id) == node_id
        ):
            raise ValidationFailedError(
                "an instance target must be a direct geometry object in the same scene",
                {"node_id": node_id, "instance_of": target_id},
            )

    world: dict[str, list[list[float]]] = {}
    effective_visible: dict[str, bool] = {}

    def world_of(node_id: str) -> list[list[float]]:
        if node_id in world:
            return world[node_id]
        node = by_id[node_id]
        parent_id = node.get("parent_id")
        local = node["transform"]
        world[node_id] = _multiply(world_of(str(parent_id)), local) if parent_id else local
        effective_visible[node_id] = bool(node.get("visible", True)) and (
            effective_visible[str(parent_id)] if parent_id else True
        )
        return world[node_id]

    resolved: list[dict[str, Any]] = []
    object_count = 0
    for raw_node in raw:
        node_id = str(raw_node["id"])
        node = by_id[node_id]
        world_matrix = world_of(node_id)
        resolved_asset_id: uuid.UUID | None = None
        asset_format: str | None = None
        if node.get("kind") == "object":
            object_count += 1
            owner = by_id[str(node["instance_of"])] if node.get("instance_of") else node
            resolved_asset_id = uuid.UUID(str(owner["asset_id"]))
            asset_format = assets[resolved_asset_id].format
        resolved.append(
            {
                **node,
                "asset_id": uuid.UUID(str(node["asset_id"])) if node.get("asset_id") else None,
                "resolved_asset_id": resolved_asset_id,
                "format": asset_format,
                "world_transform": world_matrix,
                "effective_visible": effective_visible[node_id],
            }
        )
    if nodes is not None and object_count == 0:
        raise ValidationFailedError("a scene must contain at least one geometry object")
    return resolved


def editable_object(
    db: Session,
    *,
    version: ProjectVersion,
    workspace_id: uuid.UUID,
    node_id: str,
) -> dict[str, Any]:
    """Resolve one direct object and prove its world transform preserves millimetres.

    Mesh-edit requests use world-space selections because that is what the viewport displays.
    A proper rigid transform is invertible without changing distances, angles or handedness, so
    every existing mesh operation keeps its exact millimetre meaning after conversion to the
    object's local asset.  Scaled, mirrored or sheared nodes stay viewable/exportable but need a
    future explicit bake-transform operation before component editing.
    """
    if not has_explicit_scene(version):
        raise ValidationFailedError(
            "scene_node_id is only valid for an explicit multi-object scene",
            {"scene_node_id": node_id},
        )
    target = next(
        (
            node
            for node in resolve_scene(db, version=version, workspace_id=workspace_id)
            if node["id"] == node_id
        ),
        None,
    )
    if target is None:
        raise ValidationFailedError("the scene node does not exist", {"scene_node_id": node_id})
    if target["kind"] != "object":
        raise ValidationFailedError(
            "only a geometry object can be edited", {"scene_node_id": node_id}
        )
    if target.get("instance_of") is not None:
        raise ValidationFailedError(
            "an instance must be made unique before its geometry can be edited",
            {"scene_node_id": node_id, "instance_of": target["instance_of"]},
        )
    matrix = target["world_transform"]
    linear = [row[:3] for row in matrix[:3]]
    for row in range(3):
        length = sum(linear[row][axis] ** 2 for axis in range(3))
        if abs(length - 1.0) > 1e-7:
            raise ValidationFailedError(
                "the scene node transform must be rigid before geometry editing",
                {"scene_node_id": node_id},
            )
        for other in range(row):
            dot = sum(linear[row][axis] * linear[other][axis] for axis in range(3))
            if abs(dot) > 1e-7:
                raise ValidationFailedError(
                    "the scene node transform must be rigid before geometry editing",
                    {"scene_node_id": node_id},
                )
    determinant = (
        linear[0][0] * (linear[1][1] * linear[2][2] - linear[1][2] * linear[2][1])
        - linear[0][1] * (linear[1][0] * linear[2][2] - linear[1][2] * linear[2][0])
        + linear[0][2] * (linear[1][0] * linear[2][1] - linear[1][1] * linear[2][0])
    )
    if abs(determinant - 1.0) > 1e-7:
        raise ValidationFailedError(
            "the scene node transform must preserve handedness before geometry editing",
            {"scene_node_id": node_id},
        )
    return target


def request_in_object_space(
    request: dict[str, Any], world_transform: list[list[float]]
) -> dict[str, Any]:
    """Convert all spatial fields in a mesh-edit request from world to object space."""
    rotation = [row[:3] for row in world_transform[:3]]
    translation = [world_transform[row][3] for row in range(3)]

    def coordinates(value: object) -> list[float]:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValidationFailedError("a mesh edit coordinate must have three values")
        return [float(item) for item in value]

    def vector(value: object) -> list[float]:
        source = coordinates(value)
        return [sum(rotation[axis][row] * source[axis] for axis in range(3)) for row in range(3)]

    def point(value: object) -> list[float]:
        source = [item - translation[index] for index, item in enumerate(coordinates(value))]
        return vector(source)

    def normal(value: object) -> list[float]:
        converted = vector(value)
        length = math.sqrt(sum(item * item for item in converted)) or 1.0
        return [item / length for item in converted]

    converted = {**request, "operations": []}
    for raw in request.get("operations", []):
        operation = dict(raw)
        selection = operation.get("selection")
        if isinstance(selection, dict):
            operation["selection"] = {
                **selection,
                "points_mm": [point(item) for item in selection.get("points_mm", [])],
            }
        if operation.get("delta_mm") is not None:
            operation["delta_mm"] = vector(operation["delta_mm"])
        if operation.get("at_mm") is not None:
            operation["at_mm"] = point(operation["at_mm"])
        if operation.get("normal_hint") is not None:
            operation["normal_hint"] = normal(operation["normal_hint"])
        converted["operations"].append(operation)
    return converted


def point_in_world_space(
    point: Sequence[float], world_transform: Sequence[Sequence[float]]
) -> list[float]:
    """Apply a stored affine scene transform to one object-space point."""
    return [
        sum(world_transform[row][axis] * point[axis] for axis in range(3)) + world_transform[row][3]
        for row in range(3)
    ]


def replace_object_asset(
    db: Session,
    *,
    version: ProjectVersion,
    workspace_id: uuid.UUID,
    node_id: str,
    asset_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], set[uuid.UUID]]:
    """Replace one direct node and return validated stored nodes plus every resolved asset."""
    editable_object(
        db,
        version=version,
        workspace_id=workspace_id,
        node_id=node_id,
    )
    nodes = stored_nodes(version)
    for node in nodes:
        if str(node.get("id")) == node_id:
            node["asset_id"] = str(asset_id)
            break
    resolved = resolve_scene(db, version=version, workspace_id=workspace_id, nodes=nodes)
    stored = [
        {
            "id": node["id"],
            "name": node["name"],
            "kind": node["kind"],
            "parent_id": node.get("parent_id"),
            "visible": node["visible"],
            "transform": node["transform"],
            "asset_id": str(node["asset_id"]) if node.get("asset_id") else None,
            "instance_of": node.get("instance_of"),
        }
        for node in resolved
    ]
    return stored, {
        node["resolved_asset_id"] for node in resolved if node.get("resolved_asset_id") is not None
    }


def create_scene_version(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    nodes: list[dict[str, Any]],
    label: str | None,
) -> ProjectVersion:
    source = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=source.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    source_resolved = resolve_scene(db, version=source, workspace_id=project.workspace_id)
    resolved = resolve_scene(db, version=source, workspace_id=project.workspace_id, nodes=nodes)
    stored = [
        {
            "id": node["id"],
            "name": node["name"],
            "kind": node["kind"],
            "parent_id": node.get("parent_id"),
            "visible": node["visible"],
            "transform": node["transform"],
            "asset_id": str(node["asset_id"]) if node.get("asset_id") else None,
            "instance_of": node.get("instance_of"),
        }
        for node in resolved
    ]
    old_direct = {
        str(node["id"]): node["resolved_asset_id"]
        for node in source_resolved
        if node["kind"] == "object" and node.get("instance_of") is None
    }
    new_direct = {
        str(node["id"]): node["resolved_asset_id"]
        for node in resolved
        if node["kind"] == "object" and node.get("instance_of") is None
    }
    node_map: dict[str | None, str] = {
        node_id: node_id
        for node_id, asset_id in old_direct.items()
        if new_direct.get(node_id) == asset_id
    }
    if not has_explicit_scene(source) and len(old_direct) == 1:
        (old_asset_id,) = old_direct.values()
        matches = [node_id for node_id, asset_id in new_direct.items() if asset_id == old_asset_id]
        if len(matches) == 1:
            node_map[None] = matches[0]

    prior_provenance = source.provenance or {}
    prior_metadata = prior_provenance.get("mesh_modifier_stacks")
    kept_metadata = {
        new_id: prior_metadata[old_id]
        for old_id, new_id in node_map.items()
        if old_id is not None and isinstance(prior_metadata, dict) and old_id in prior_metadata
    }
    legacy_metadata = prior_provenance.get("mesh_modifier_stack")
    if None in node_map and isinstance(legacy_metadata, dict):
        kept_metadata[node_map[None]] = legacy_metadata

    provenance = {
        **(source.provenance or {}),
        "operation": "edit_scene",
        "scene": {"schema_version": SCENE_SCHEMA_VERSION, "nodes": stored},
        "scene_edit": {"source_version_id": str(source.id), "node_count": len(stored)},
        "mesh_modifier_stacks": kept_metadata,
    }
    provenance.pop("mesh_modifier_stack", None)
    made = projects.create_version_internal(
        db,
        project_id=project.id,
        parent_version_id=source.id,
        label=label or "Scene edit",
        provenance=provenance,
        finalize=False,
        created_by=user_id,
    )
    asset_ids = {node["resolved_asset_id"] for node in resolved if node["resolved_asset_id"]}
    for asset_id in asset_ids:
        projects.attach_asset(
            db, made, asset_id, AssetRole.model, workspace_id=project.workspace_id
        )
    rows = db.scalars(
        sa.select(MeshModifier)
        .where(MeshModifier.project_version_id == source.id)
        .order_by(MeshModifier.sequence_no)
    ).all()
    sequence_no = 0
    for row in rows:
        mapped = node_map.get(row.scene_node_id)
        if mapped is None:
            continue
        sequence_no += 1
        db.add(
            MeshModifier(
                project_version_id=made.id,
                sequence_no=sequence_no,
                scene_node_id=mapped,
                modifier_key=row.modifier_key,
                modifier_type=row.modifier_type,
                enabled=row.enabled,
                tolerance_mm=row.tolerance_mm,
                params=row.params,
            )
        )
    db.flush()
    projects.finalize_version(db, made)
    db.refresh(made)
    return made
