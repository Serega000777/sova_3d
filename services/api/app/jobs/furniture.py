"""Create one furniture mesh and append it to an immutable scene version."""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict
from typing import Any, cast

import sqlalchemy as sa
from worker.furniture import FurnitureKind, build_stl

from app.api.errors import APIError
from app.furniture_catalog import BY_KIND
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Project
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import furniture as furniture_service
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
    clearance = ctx.job.input.get("clearance_mm")
    floor_plan_id = ctx.job.input.get("floor_plan_id")
    if clearance is not None or floor_plan_id is not None:
        if clearance is None or not isinstance(floor_plan_id, str):
            raise JobFailureError(
                "invalid_furniture", "floor_plan_id and clearance_mm must be provided together"
            )
        project = ctx.db.get(Project, version.project_id)
        if project is None:
            raise JobFailureError("project_not_found", str(version.project_id))
        # Keep the head proof and scene mutation in one transaction. Without this lock, two
        # workers could both validate the same source and the second one would create a stale
        # branch after the first placement advanced the head.
        ctx.db.execute(sa.select(Project.id).where(Project.id == project.id).with_for_update())
        ctx.db.refresh(project)
        try:
            plan = furniture_service.placement_plan(
                ctx.job.input.get("floor_plan"), expected_id=floor_plan_id
            )
            furniture_service.validate_plan_placement(
                ctx.db,
                project=project,
                version=version,
                plan=plan,
                floor_plan_id=floor_plan_id,
                kind=kind,
                x_mm=float(ctx.job.input.get("x_mm", 0)),
                y_mm=float(ctx.job.input.get("y_mm", 0)),
                width_mm=width,
                depth_mm=depth,
                rotation_deg=float(ctx.job.input.get("rotation_deg", 0)),
                clearance_mm=float(clearance),
            )
        except APIError as exc:
            raise JobFailureError(
                "furniture_placement_conflict", exc.message, details=exc.details
            ) from exc
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
            "footprint_mm": [width, depth],
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


@register(furniture_service.AUTO_FURNISH_JOB)
def handle_auto_furnish_floor_plan(ctx: JobContext) -> dict[str, Any]:
    """Build a typed plan's deterministic starter furniture in one immutable scene version."""
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None or version.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    project = ctx.db.get(Project, version.project_id)
    if project is None:
        raise JobFailureError("project_not_found", str(version.project_id))
    floor_plan_id = ctx.job.input.get("floor_plan_id")
    if not isinstance(floor_plan_id, str):
        raise JobFailureError("invalid_furniture", "floor_plan_id is required")

    ctx.db.execute(sa.select(Project.id).where(Project.id == project.id).with_for_update())
    ctx.db.refresh(project)
    if project.head_version_id != version.id:
        raise JobFailureError(
            "furniture_placement_conflict",
            "the project changed; reload before generating furniture",
            details={"head_version_id": str(project.head_version_id)},
        )
    try:
        plan = furniture_service.placement_plan(
            ctx.job.input.get("floor_plan"), expected_id=floor_plan_id
        )
        canonical = furniture_service.placement_plan(
            (version.provenance or {}).get("floor_plan"), expected_id=floor_plan_id
        )
        if canonical.model_dump(mode="json") != plan.model_dump(mode="json"):
            raise ValueError("the furniture job plan does not match its immutable version")
        placements = furniture_service.plan_auto_furniture(
            plan,
            existing=furniture_service.scene_footprints(
                ctx.db, version=version, workspace_id=project.workspace_id
            ),
        )
    except APIError as exc:
        raise JobFailureError(
            "furniture_placement_conflict", exc.message, details=exc.details
        ) from exc
    except (TypeError, ValueError) as exc:
        raise JobFailureError("invalid_furniture", str(exc)) from exc
    expected_input = [asdict(item) for item in placements]
    if ctx.job.input.get("placements") != expected_input:
        raise JobFailureError(
            "invalid_furniture", "automatic furniture placements are not canonical"
        )

    assets: dict[tuple[str, float, float, float], Any] = {}
    nodes = scenes.stored_nodes(version)
    made_asset_ids: list[str] = []
    for index, placement in enumerate(placements):
        key = (
            placement.kind,
            placement.width_mm,
            placement.depth_mm,
            placement.height_mm,
        )
        asset = assets.get(key)
        if asset is None:
            try:
                data = build_stl(
                    cast(FurnitureKind, placement.kind),
                    placement.width_mm,
                    placement.depth_mm,
                    placement.height_mm,
                )
            except (TypeError, ValueError) as exc:
                raise JobFailureError("invalid_furniture", str(exc)) from exc
            asset = store_derived_asset(
                ctx,
                workspace_id=ctx.job.workspace_id,
                data=data,
                format_id="stl",
                metadata={
                    "operation": furniture_service.AUTO_FURNISH_JOB,
                    "kind": placement.kind,
                    "dimensions_mm": {
                        "width": placement.width_mm,
                        "depth": placement.depth_mm,
                        "height": placement.height_mm,
                    },
                },
                created_by=ctx.job.created_by,
            )
            assets[key] = asset
            ctx.db.add(
                JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value)
            )
            made_asset_ids.append(str(asset.id))
        angle = math.radians(placement.rotation_deg)
        cosine, sine = math.cos(angle), math.sin(angle)
        nodes.append(
            {
                "id": (
                    f"auto_furniture_{placement.room_index}_{placement.kind}_{uuid.uuid4().hex[:8]}"
                ),
                "name": f"{BY_KIND[placement.kind]['name']} · {placement.room_name}",
                "kind": "object",
                "parent_id": None,
                "visible": True,
                "transform": [
                    [cosine, -sine, 0, placement.x_mm],
                    [sine, cosine, 0, placement.y_mm],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ],
                "asset_id": str(asset.id),
                "instance_of": None,
                "footprint_mm": [placement.width_mm, placement.depth_mm],
            }
        )
        ctx.progress(20 + round(60 * (index + 1) / len(placements)), "building furniture")

    if ctx.job.created_by is None:
        raise JobFailureError("creator_missing", "automatic furniture needs an owning user")
    made = scenes.create_scene_version(
        ctx.db,
        user_id=ctx.job.created_by,
        version_id=version.id,
        nodes=nodes,
        label="Auto-furnish typed floor plan",
    )
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "floor_plan_id": floor_plan_id,
        "placed": len(placements),
        "asset_ids": made_asset_ids,
    }
