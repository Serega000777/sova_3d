"""`ai_command` job handler (T-045): plan -> validate -> execute in the kernel -> version.

Failure modes are explicit and user-safe:
- needs_clarification: the job parks in waiting_input (T-042) until the user answers;
- rejected/refused: the plan never reached the kernel;
- kernel errors: reported per operation (id, type, code) — never a corrupted model.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.ai.planner import plan_with_repair, planner_for
from app.config import load_settings
from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, JobWaitingForInputError, register
from app.models.execution import AIRequest, AIRequestStatus, JobArtifact, Operation
from app.models.versioning import AssetRole
from app.services import ai_commands, projects


@register("ai_command")
def handle_ai_command(ctx: JobContext) -> dict[str, Any]:
    settings = load_settings()
    request_id = uuid.UUID(str(ctx.job.input["ai_request_id"]))
    request = ctx.db.get(AIRequest, request_id)
    if request is None:
        raise JobFailureError("ai_request_not_found", str(request_id))
    if request.project_id is None:
        raise JobFailureError("no_project", "request has no project")

    # --- plan --------------------------------------------------------------------------------
    request.status = AIRequestStatus.planning
    ctx.progress(10, "planning")
    outcome = plan_with_repair(planner_for(settings), ai_commands.plan_request_for(ctx.db, request))
    ai_commands.record_usage(ctx.db, request, outcome.usage, ctx.job.id)
    ctx.job.cost_usd = (ctx.job.cost_usd or 0) + outcome.cost_usd
    if outcome.cost_usd > settings.ai_budget_usd_per_job:
        request.status = AIRequestStatus.failed
        raise JobFailureError(
            "ai_budget_exceeded",
            f"planning cost {outcome.cost_usd} USD exceeds the per-job budget",
        )
    raw = outcome.raw_output
    request.output_plan = raw.model_dump() if raw else None

    if outcome.status == "refused":
        request.status = AIRequestStatus.rejected
        request.plan_errors = [outcome.refusal or "declined"]
        raise JobFailureError("plan_refused", outcome.refusal or "the planner declined")
    if outcome.status == "rejected":
        request.status = AIRequestStatus.rejected
        request.plan_errors = outcome.errors
        raise JobFailureError(
            "plan_rejected",
            "the planner could not produce a valid plan",
            details={"errors": outcome.errors},
        )
    if outcome.status == "needs_clarification":
        request.status = AIRequestStatus.needs_clarification
        request.clarifications = outcome.clarifications
        ctx.db.flush()
        raise JobWaitingForInputError(
            {
                "ai_request_id": str(request.id),
                "status": "needs_clarification",
                "clarifications": outcome.clarifications,
            }
        )

    plan = outcome.plan
    assert plan is not None
    request.status = AIRequestStatus.planned
    request.output_plan = plan.model_dump(mode="json")
    ctx.db.flush()
    ctx.progress(35, "planned")

    # --- execute -----------------------------------------------------------------------------
    try:
        executed = run_plan(plan)
    except JobFailureError as exc:
        request.status = AIRequestStatus.failed
        request.plan_errors = [str(exc.details.get("kernel_message") or exc.message)]
        raise
    ctx.progress(70, "executed")
    main = executed.main

    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=request.workspace_id,
        created_by=request.user_id,
    )
    tag = {"ai_request_id": str(request.id)}
    model_asset = store(
        data=executed.stl, format_id="stl", metadata={**tag, "body": main.name, "kind": "mesh"}
    )
    source_asset = store(
        data=executed.brep, format_id="brep", metadata={**tag, "body": main.name, "kind": "brep"}
    )
    ctx.progress(85, "uploaded")

    # --- version -----------------------------------------------------------------------------
    bodies = executed.bodies
    version = projects.create_version_internal(
        ctx.db,
        project_id=request.project_id,
        parent_version_id=request.project_version_id,
        label=plan.goal[:200],
        provenance={
            "ai_request_id": str(request.id),
            "job_id": str(ctx.job.id),
            "operation": "ai_command",
            "kernel": executed.kernel,
            "plan_goal": plan.goal,
            "assumptions": plan.assumptions,
            "validation_steps": plan.validation_steps,
            "bodies": bodies,
        },
        assets={AssetRole.model: model_asset.id, AssetRole.source: source_asset.id},
        finalize=False,
        created_by=request.user_id,
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
                ai_request_id=request.id,
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, version)
    for asset in (model_asset, source_asset):
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))

    request.status = AIRequestStatus.executed
    request.result_version_id = version.id
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "ai_request_id": str(request.id),
        "status": "executed",
        "version_id": str(version.id),
        "model_asset_id": str(model_asset.id),
        "source_asset_id": str(source_asset.id),
        "plan": plan.model_dump(mode="json"),
        "bodies": bodies,
        "cost_usd": str(outcome.cost_usd),
    }
