"""Create one furniture mesh and append it to an immutable scene version."""

from __future__ import annotations

import math
import uuid
from typing import Any, cast

from worker.furniture import FurnitureKind, build_stl

from app.furniture_catalog import BY_KIND
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import scenes


@register("place_furniture")
def handle_place_furniture(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None or version.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    kind = str(ctx.job.input["kind"])
    if kind not in BY_KIND:
        raise JobFailureError("invalid_furniture", f"unsupported furniture kind {kind!r}")
    width = float(ctx.job.input["width_mm"])
    depth = float(ctx.job.input["depth_mm"])
    height = float(ctx.job.input["height_mm"])
    try:
        data = build_stl(cast(FurnitureKind, kind), width, depth, height)
    except (TypeError, ValueError) as exc:
        raise JobFailureError("invalid_furniture", str(exc)) from exc
    ctx.progress(40, "built")
    asset = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=data,
        format_id="stl",
        metadata={
            "operation": "place_furniture",
            "kind": kind,
            "dimensions_mm": {"width": width, "depth": depth, "height": height},
        },
        created_by=ctx.job.created_by,
    )
    angle = math.radians(float(ctx.job.input.get("rotation_deg", 0)))
    cosine, sine = math.cos(angle), math.sin(angle)
    node_id = f"furniture_{kind}_{uuid.uuid4().hex[:12]}"
    nodes = scenes.stored_nodes(version)
    nodes.append(
        {
            "id": node_id,
            "name": BY_KIND[kind]["name"],
            "kind": "object",
            "parent_id": None,
            "visible": True,
            "transform": [
                [cosine, -sine, 0, float(ctx.job.input.get("x_mm", 0))],
                [sine, cosine, 0, float(ctx.job.input.get("y_mm", 0))],
                [0, 0, 1, float(ctx.job.input.get("z_mm", 0))],
                [0, 0, 0, 1],
            ],
            "asset_id": str(asset.id),
            "instance_of": None,
        }
    )
    if ctx.job.created_by is None:
        raise JobFailureError("creator_missing", "furniture placement needs an owning user")
    made = scenes.create_scene_version(
        ctx.db,
        user_id=ctx.job.created_by,
        version_id=version.id,
        nodes=nodes,
        label=f"Add {BY_KIND[kind]['name']}",
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "node_id": node_id,
        "asset_id": str(asset.id),
    }
