"""Execute a house-box operation plan and save a finalized project version."""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.engineering.floor_plan import floor_plan_from_house_box
from app.engineering.house_box import HouseBoxRequest
from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import AssetRole
from app.services import projects
from app.services.house_boxes import HOUSE_BOX_JOB


@register(HOUSE_BOX_JOB)
def handle_house_box(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    try:
        request = HouseBoxRequest(**dict(ctx.job.input.get("request") or {}))
        plan = request.build()
    except (TypeError, ValueError) as exc:
        raise JobFailureError("invalid_house_box", str(exc)) from exc
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
    ctx.progress(85, "uploaded")

    request_data = {
        "length_mm": request.length_mm,
        "width_mm": request.width_mm,
        "floor_height_mm": request.floor_height_mm,
        "floors": request.floors,
        "shape": request.shape,
    }
    floor_plan = floor_plan_from_house_box(
        request,
        plan_id=f"project-{project_id}-floor-1",
        name=str(ctx.job.input.get("label") or "House plan")[:200],
    ).model_dump(mode="json")
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
    for asset in (model_asset, source_asset):
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
        "house_box": {"request": request_data, "height_mm": height_mm},
        "status": "executed",
    }
