"""Execute a house-box operation plan and save a finalized project version."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from functools import partial
from typing import Any

from app.api.errors import ValidationFailedError
from app.engineering.floor_plan import floor_plan_from_house_box, floor_plans_from_house_box
from app.engineering.house_box import HouseBoxRequest
from app.interior_materials import material_by_id, snapshot_for
from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import AssetRole
from app.services import projects, scenes
from app.services.house_boxes import HOUSE_BOX_JOB


@register(HOUSE_BOX_JOB)
def handle_house_box(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    try:
        request = HouseBoxRequest(**dict(ctx.job.input.get("request") or {}))
        if request.stair is not None and request.stair.material_id is not None:
            material_by_id(request.stair.material_id)
        plan = request.build()
    except (TypeError, ValueError, ValidationFailedError) as exc:
        message = exc.message if isinstance(exc, ValidationFailedError) else str(exc)
        raise JobFailureError("invalid_house_box", message) from exc
    ctx.progress(15, "planned")

    executed = run_plan(plan)
    ctx.progress(70, "executed")
    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=ctx.job.workspace_id,
        created_by=ctx.job.created_by,
    )
    tag = {"operation": HOUSE_BOX_JOB, "job_id": str(ctx.job.id)}

    request_data = {
        "length_mm": request.length_mm,
        "width_mm": request.width_mm,
        "floor_height_mm": request.floor_height_mm,
        "floors": request.floors,
        "shape": request.shape,
        "stair": asdict(request.stair) if request.stair is not None else None,
    }
    floor_plan = floor_plan_from_house_box(
        request,
        plan_id=f"project-{project_id}-floor-1",
        name=str(ctx.job.input.get("label") or "House plan")[:200],
    ).model_dump(mode="json")
    if request.stair is not None:
        missing = set(plan.expected_outputs) - set(executed.parts)
        if missing:
            raise JobFailureError(
                "kernel_bad_output",
                "the geometry engine did not return every floor and stair body",
                details={"missing_bodies": sorted(missing)},
            )
        part_assets: dict[str, tuple[Any, Any]] = {}
        for body_name in plan.expected_outputs:
            stl, brep = executed.parts[body_name]
            part_assets[body_name] = (
                store(
                    data=stl,
                    format_id="stl",
                    metadata={**tag, "body": body_name, "kind": "mesh"},
                ),
                store(
                    data=brep,
                    format_id="brep",
                    metadata={**tag, "body": body_name, "kind": "brep"},
                ),
            )
        appearance = (
            snapshot_for(material_by_id(request.stair.material_id))
            if request.stair.material_id is not None
            else None
        )
        nodes: list[dict[str, Any]] = []
        for floor_index in range(request.floors):
            group_id = f"floor_{floor_index + 1}_group"
            floor_body = f"floor_{floor_index + 1}"
            nodes.extend(
                [
                    {
                        "id": group_id,
                        "name": f"{floor_index + 1} этаж",
                        "kind": "group",
                        "parent_id": None,
                        "visible": True,
                        "transform": scenes.IDENTITY,
                        "asset_id": None,
                        "instance_of": None,
                        "footprint_mm": None,
                        "appearance": None,
                    },
                    {
                        "id": floor_body,
                        "name": f"Оболочка · {floor_index + 1} этаж",
                        "kind": "object",
                        "parent_id": group_id,
                        "visible": True,
                        "transform": scenes.IDENTITY,
                        "asset_id": str(part_assets[floor_body][0].id),
                        "instance_of": None,
                        "footprint_mm": None,
                        "appearance": None,
                    },
                ]
            )
            if floor_index >= request.floors - 1:
                continue
            flight_prefix = f"stair_{floor_index + 1}_{floor_index + 2}"
            flight_body = f"{flight_prefix}_step_1"
            nodes.append(
                {
                    "id": flight_prefix,
                    "name": f"Лестница {floor_index + 1} → {floor_index + 2}",
                    "kind": "object",
                    "parent_id": group_id,
                    "visible": True,
                    "transform": scenes.IDENTITY,
                    "asset_id": str(part_assets[flight_body][0].id),
                    "instance_of": None,
                    "footprint_mm": None,
                    "appearance": appearance,
                }
            )
            if request.stair.railing:
                for side in ("left", "right"):
                    rail_body = f"rail_{side}_{floor_index + 1}_{floor_index + 2}"
                    nodes.append(
                        {
                            "id": rail_body,
                            "name": (
                                f"Ограждение {'левое' if side == 'left' else 'правое'} · "
                                f"{floor_index + 1} этаж"
                            ),
                            "kind": "object",
                            "parent_id": group_id,
                            "visible": True,
                            "transform": scenes.IDENTITY,
                            "asset_id": str(part_assets[rail_body][0].id),
                            "instance_of": None,
                            "footprint_mm": None,
                            "appearance": appearance,
                        }
                    )
        nodes.extend(
            [
                {
                    "id": "roof_group",
                    "name": "Крыша",
                    "kind": "group",
                    "parent_id": None,
                    "visible": True,
                    "transform": scenes.IDENTITY,
                    "asset_id": None,
                    "instance_of": None,
                    "footprint_mm": None,
                    "appearance": None,
                },
                {
                    "id": "roof",
                    "name": "Плоская крыша",
                    "kind": "object",
                    "parent_id": "roof_group",
                    "visible": True,
                    "transform": scenes.IDENTITY,
                    "asset_id": str(part_assets["roof"][0].id),
                    "instance_of": None,
                    "footprint_mm": None,
                    "appearance": None,
                },
            ]
        )
        version = projects.create_version_internal(
            ctx.db,
            project_id=project_id,
            label=str(ctx.job.input.get("label") or plan.goal)[:200],
            provenance={
                **tag,
                "kernel": executed.kernel,
                "plan_goal": plan.goal,
                "assumptions": plan.assumptions,
                "bodies": executed.bodies,
                "expected_outputs": list(plan.expected_outputs),
                "floor_plan": floor_plan,
                "house_box": {
                    "request": request_data,
                    "height_mm": request.floor_height_mm * request.floors,
                },
                "scene": {"schema_version": scenes.SCENE_SCHEMA_VERSION, "nodes": nodes},
            },
            finalize=False,
            created_by=ctx.job.created_by,
        )
        floor_plans = floor_plans_from_house_box(
            request,
            project_id=str(project_id),
            version_id=str(version.id),
            name=str(ctx.job.input.get("label") or "House plan")[:120],
        ).model_dump(mode="json")
        version.provenance = {**(version.provenance or {}), "floor_plans": floor_plans}
        attached: set[tuple[uuid.UUID, AssetRole]] = set()
        for model_asset, source_part_asset in part_assets.values():
            if (model_asset.id, AssetRole.model) not in attached:
                projects.attach_asset(
                    ctx.db,
                    version,
                    model_asset.id,
                    AssetRole.model,
                    workspace_id=ctx.job.workspace_id,
                )
                attached.add((model_asset.id, AssetRole.model))
            if (source_part_asset.id, AssetRole.source) in attached:
                continue
            projects.attach_asset(
                ctx.db,
                version,
                source_part_asset.id,
                AssetRole.source,
                workspace_id=ctx.job.workspace_id,
            )
            attached.add((source_part_asset.id, AssetRole.source))
        model_asset = part_assets["floor_1"][0]
        artifact_assets = list(
            {asset.id: asset for pair in part_assets.values() for asset in pair}.values()
        )
    else:
        model_asset = store(
            data=executed.stl,
            format_id="stl",
            metadata={**tag, "body": executed.main.name, "kind": "mesh"},
        )
        source_asset = store(
            data=executed.brep,
            format_id="brep",
            metadata={**tag, "body": executed.main.name, "kind": "brep"},
        )
        version = projects.create_version_internal(
            ctx.db,
            project_id=project_id,
            label=str(ctx.job.input.get("label") or plan.goal)[:200],
            provenance={
                **tag,
                "kernel": executed.kernel,
                "plan_goal": plan.goal,
                "assumptions": plan.assumptions,
                "bodies": executed.bodies,
                "expected_outputs": list(plan.expected_outputs),
                "floor_plan": floor_plan,
                "house_box": {
                    "request": request_data,
                    "height_mm": request.floor_height_mm * request.floors,
                },
            },
            assets={AssetRole.model: model_asset.id, AssetRole.source: source_asset.id},
            finalize=False,
            created_by=ctx.job.created_by,
        )
        artifact_assets = [model_asset, source_asset]
    ctx.progress(85, "uploaded")
    for index, operation in enumerate(plan.operations, start=1):
        ctx.db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=index,
                operation_type=operation.type,
                schema_version=1,
                params=operation.model_dump(mode="json"),
                entity_refs=[ref for ref in (getattr(operation, "target", None),) if ref],
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, version)
    for asset in artifact_assets:
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))
    ctx.db.flush()
    ctx.progress(100, "done")
    height_mm = request.floor_height_mm * request.floors
    return {
        "version_id": str(version.id),
        "project_id": str(project_id),
        "model_asset_id": str(model_asset.id),
        "bodies": executed.bodies,
        "floor_plan": floor_plan,
        "floor_plans": (version.provenance or {}).get("floor_plans"),
        "house_box": {"request": request_data, "height_mm": height_mm},
        "status": "executed",
    }
