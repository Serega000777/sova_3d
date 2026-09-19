"""`build_enclosure` job (T-157, F-036): the generated plan through the kernel, the tray as
the version's model, the lid as a part of its own, the plan as the version's editable log."""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.engineering import enclosure
from app.geometry.operations import parse_plan
from app.jobs.artifacts import store_derived_asset, store_extra_parts
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import AIRequest, AIRequestStatus, JobArtifact, Operation
from app.models.versioning import AssetRole
from app.services import projects
from app.services.enclosures import ENCLOSURE_JOB


@register(ENCLOSURE_JOB)
def handle_enclosure(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    request_id = ctx.job.input.get("ai_request_id")
    request = ctx.db.get(AIRequest, uuid.UUID(str(request_id))) if request_id else None
    try:
        spec = enclosure.EnclosureRequest(**dict(ctx.job.input.get("request") or {}))
        built = enclosure.build(spec)
        plan = parse_plan(built.plan)
    except (KeyError, TypeError, ValueError) as exc:
        raise JobFailureError("invalid_enclosure", str(exc)) from exc
    ctx.progress(15, "planned")

    try:
        executed = run_plan(plan)
    except JobFailureError:
        if request is not None:
            request.status = AIRequestStatus.failed
            ctx.db.flush()
        raise
    ctx.progress(70, "executed")
    main = executed.main
    store = partial(
        store_derived_asset, ctx, workspace_id=ctx.job.workspace_id, created_by=ctx.job.created_by
    )
    tag = {"operation": ENCLOSURE_JOB, "job_id": str(ctx.job.id)}
    model_asset = store(
        data=executed.stl, format_id="stl", metadata={**tag, "body": main.name, "kind": "mesh"}
    )
    source_asset = store(
        data=executed.brep, format_id="brep", metadata={**tag, "body": main.name, "kind": "brep"}
    )
    parts = store_extra_parts(
        ctx, executed, workspace_id=ctx.job.workspace_id, created_by=ctx.job.created_by, tag=tag
    )
    ctx.progress(85, "uploaded")

    label = str(ctx.job.input.get("label") or built.plan["goal"])
    version = projects.create_version_internal(
        ctx.db,
        project_id=project_id,
        label=label[:200],
        provenance={
            **tag,
            "kernel": executed.kernel,
            "plan_goal": plan.goal,
            "assumptions": plan.assumptions,
            "bodies": executed.bodies,
            "expected_outputs": list(plan.expected_outputs),
            "parts": parts,
            "component_id": spec.component_id,
            "enclosure": {
                "outer_mm": list(built.outer_mm),
                "inner_mm": list(built.inner_mm),
                "posts": built.posts,
                "cutouts": built.cutouts,
                "lid": built.lid,
                "fan": built.fan,
                "notes": built.notes,
                "request": spec.__dict__,
            },
            "ai_request_id": str(request.id) if request else None,
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
                ai_request_id=request.id if request else None,
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, version)
    for asset in (model_asset, source_asset):
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))
    if request is not None:
        request.status = AIRequestStatus.executed
        request.result_version_id = version.id
        request.output_plan = plan.model_dump(mode="json")
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "project_id": str(project_id),
        "model_asset_id": str(model_asset.id),
        "parts": parts,
        "bodies": executed.bodies,
        "enclosure": {
            "outer_mm": list(built.outer_mm),
            "posts": built.posts,
            "cutouts": built.cutouts,
            "lid": built.lid,
            "fan": built.fan,
            "notes": built.notes,
        },
        "ai_request_id": str(request.id) if request else None,
        "status": "executed",
    }
