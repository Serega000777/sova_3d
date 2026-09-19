"""`execute_plan` job: build a version from a plan the platform itself authored.

Calibration coupons (F-029) and other deterministic parts need neither a planner nor a
user edit — just the kernel. The result is an ordinary version with its operation log,
so everything downstream (edits, paint, the engineer, exports) treats it like any other.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.geometry.operations import parse_plan
from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import AssetRole
from app.services import projects
from app.services.calibration import EXECUTE_PLAN_JOB


@register(EXECUTE_PLAN_JOB)
def handle_execute_plan(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    try:
        plan = parse_plan(ctx.job.input["plan"])
    except (KeyError, ValueError) as exc:
        raise JobFailureError("invalid_plan", str(exc)) from exc
    label: str | None = ctx.job.input.get("label")
    provenance_extra: dict[str, Any] = dict(ctx.job.input.get("provenance") or {})

    executed = run_plan(plan)
    ctx.progress(70, "executed")
    main = executed.main

    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=ctx.job.workspace_id,
        created_by=ctx.job.created_by,
    )
    tag = {"operation": EXECUTE_PLAN_JOB, "job_id": str(ctx.job.id)}
    model_asset = store(
        data=executed.stl, format_id="stl", metadata={**tag, "body": main.name, "kind": "mesh"}
    )
    source_asset = store(
        data=executed.brep, format_id="brep", metadata={**tag, "body": main.name, "kind": "brep"}
    )
    ctx.progress(85, "uploaded")

    version = projects.create_version_internal(
        ctx.db,
        project_id=project_id,
        parent_version_id=None,
        label=(label or plan.goal)[:200],
        provenance={
            "operation": EXECUTE_PLAN_JOB,
            "job_id": str(ctx.job.id),
            "kernel": executed.kernel,
            "plan_goal": plan.goal,
            "bodies": executed.bodies,
            **provenance_extra,
        },
        assets={AssetRole.model: model_asset.id, AssetRole.source: source_asset.id},
        finalize=False,
        created_by=ctx.job.created_by,
    )
    for index, operation in enumerate(plan.operations, start=1):
        params = operation.model_dump(mode="json")
        ctx.db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=index,
                operation_type=operation.type,
                schema_version=1,
                params=params,
                entity_refs=[ref for ref in (getattr(operation, "target", None),) if ref],
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, version)
    for asset in (model_asset, source_asset):
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "model_asset_id": str(model_asset.id),
        "source_asset_id": str(source_asset.id),
        "plan": plan.model_dump(mode="json"),
        "bodies": executed.bodies,
    }
