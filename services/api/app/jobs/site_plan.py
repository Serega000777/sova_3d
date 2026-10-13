"""Build terrain/path/fence meshes and place an existing exact house as one immutable scene."""

from __future__ import annotations

import math
import uuid
from typing import Any

import sqlalchemy as sa
from worker.site_plan import build_fence_stl, build_pad_stl, build_path_stl, build_terrain_stl

from app.api.errors import APIError
from app.interior_materials import material_by_id, snapshot_for
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Project
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import scenes, site_plans


def _object_node(node_id: str, name: str, asset_id: uuid.UUID, parent_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": name,
        "kind": "object",
        "parent_id": parent_id,
        "visible": True,
        "transform": [row[:] for row in scenes.IDENTITY],
        "asset_id": str(asset_id),
        "instance_of": None,
        "footprint_mm": None,
    }


@register(site_plans.SITE_PLAN_JOB)
def handle_site_plan(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None or version.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    project = ctx.db.get(Project, version.project_id)
    if project is None:
        raise JobFailureError("project_not_found", str(version.project_id))
    ctx.db.execute(sa.select(Project.id).where(Project.id == project.id).with_for_update())
    ctx.db.refresh(project)
    raw_spec = ctx.job.input.get("spec")
    if not isinstance(raw_spec, dict):
        raise JobFailureError("invalid_site_plan", "site plan specification is missing")
    try:
        spec = site_plans.validate_spec(project=project, version=version, spec=raw_spec)
        terrain_data = build_terrain_stl(
            float(spec["plot_length_mm"]),
            float(spec["plot_width_mm"]),
            spec["corner_elevations_mm"],
        )
        pad_data = build_pad_stl(
            float(spec["house"]["length_mm"]) + 1_000,
            float(spec["house"]["width_mm"]) + 1_000,
            float(spec["pad_height_mm"]),
        )
        path_data = build_path_stl(
            spec["path_points_mm"],
            float(spec["path_width_mm"]),
            plot_length_mm=float(spec["plot_length_mm"]),
            plot_width_mm=float(spec["plot_width_mm"]),
            elevations_mm=spec["corner_elevations_mm"],
        )
        fence_data = (
            build_fence_stl(
                float(spec["plot_length_mm"]),
                float(spec["plot_width_mm"]),
                spec["fence_sides"],
                float(spec["fence_height_mm"]),
                float(spec["fence_post_spacing_mm"]),
                spec["corner_elevations_mm"],
            )
            if spec["fence_sides"]
            else None
        )
    except APIError as exc:
        raise JobFailureError("site_plan_conflict", exc.message, details=exc.details) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise JobFailureError("invalid_site_plan", str(exc)) from exc
    ctx.progress(35, "built site meshes")

    made_assets: dict[str, Any] = {}
    for name, payload in (
        ("terrain", terrain_data),
        ("pad", pad_data),
        ("path", path_data),
        ("fence", fence_data),
    ):
        if payload is None:
            continue
        asset = store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=payload,
            format_id="stl",
            metadata={"operation": site_plans.SITE_PLAN_JOB, "site_role": name},
            created_by=ctx.job.created_by,
        )
        made_assets[name] = asset
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.progress(65, "stored site meshes")

    angle = math.radians(float(spec["house_rotation_deg"]))
    cosine, sine = math.cos(angle), math.sin(angle)
    nodes = scenes.stored_nodes(version)
    for node in nodes:
        if node.get("parent_id") is None:
            node["parent_id"] = "site_house"
    nodes.extend(
        [
            {
                "id": "site_root",
                "name": "Участок",
                "kind": "group",
                "parent_id": None,
                "visible": True,
                "transform": [row[:] for row in scenes.IDENTITY],
                "asset_id": None,
                "instance_of": None,
                "footprint_mm": None,
            },
            {
                "id": "site_house",
                "name": "Дом на участке",
                "kind": "group",
                "parent_id": "site_root",
                "visible": True,
                "transform": [
                    [cosine, -sine, 0, float(spec["house_x_mm"])],
                    [sine, cosine, 0, float(spec["house_y_mm"])],
                    [0, 0, 1, float(spec["house_z_mm"])],
                    [0, 0, 0, 1],
                ],
                "asset_id": None,
                "instance_of": None,
                "footprint_mm": None,
            },
            _object_node("site_terrain", "Рельеф участка", made_assets["terrain"].id, "site_root"),
            {
                **_object_node(
                    "site_house_pad", "Площадка дома", made_assets["pad"].id, "site_root"
                ),
                "transform": [
                    [cosine, -sine, 0, float(spec["house_x_mm"])],
                    [sine, cosine, 0, float(spec["house_y_mm"])],
                    [0, 0, 1, float(spec["pad_bottom_mm"])],
                    [0, 0, 0, 1],
                ],
            },
            _object_node("site_path", "Дорожка", made_assets["path"].id, "site_root"),
        ]
    )
    if "fence" in made_assets:
        nodes.append(_object_node("site_fence", "Ограждение", made_assets["fence"].id, "site_root"))
    if ctx.job.created_by is None:
        raise JobFailureError("creator_missing", "site composition needs an owning user")
    details = {
        "schema_version": 1,
        "source_version_id": str(version.id),
        "plot_length_mm": spec["plot_length_mm"],
        "plot_width_mm": spec["plot_width_mm"],
        "corner_elevations_mm": spec["corner_elevations_mm"],
        "house_x_mm": spec["house_x_mm"],
        "house_y_mm": spec["house_y_mm"],
        "house_rotation_deg": spec["house_rotation_deg"],
        "house_z_mm": spec["house_z_mm"],
        "pad_bottom_mm": spec["pad_bottom_mm"],
        "path_points_mm": spec["path_points_mm"],
        "path_width_mm": spec["path_width_mm"],
        "fence_sides": spec["fence_sides"],
        "fence_height_mm": spec["fence_height_mm"],
        "fence_post_spacing_mm": spec["fence_post_spacing_mm"],
        "house_dimensions_mm": [spec["house"]["length_mm"], spec["house"]["width_mm"]],
    }
    made = scenes.create_scene_version(
        ctx.db,
        user_id=ctx.job.created_by,
        version_id=version.id,
        nodes=nodes,
        label="Участок вокруг дома",
        operation="site_plan",
        operation_details=details,
        appearance_overrides={
            "site_terrain": snapshot_for(material_by_id("interior.paint.sage-matte.v1")),
            "site_path": snapshot_for(material_by_id("interior.stone.grey-v1")),
            "site_house_pad": snapshot_for(material_by_id("interior.stone.grey-v1")),
            **(
                {"site_fence": snapshot_for(material_by_id("interior.paint.graphite-satin.v1"))}
                if "fence" in made_assets
                else {}
            ),
        },
    )
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "site_node_id": "site_root",
        "asset_ids": {name: str(asset.id) for name, asset in made_assets.items()},
        "site_plan": details,
    }
