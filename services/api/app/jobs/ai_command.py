"""`ai_command` job handler (T-045): plan -> validate -> execute in the kernel -> version.

Failure modes are explicit and user-safe:
- needs_clarification: the job parks in waiting_input (T-042) until the user answers;
- rejected/refused: the plan never reached the kernel;
- kernel errors: reported per operation (id, type, code) — never a corrupted model.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import geometry as kernel

from app import formats
from app.ai.planner import plan_with_repair, planner_for
from app.config import load_settings
from app.jobs.runner import JobContext, JobFailureError, JobWaitingForInputError, register
from app.models.core import Units
from app.models.execution import AIRequest, AIRequestStatus, JobArtifact, Operation
from app.models.versioning import Asset, AssetKind, AssetRole
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
    with tempfile.TemporaryDirectory(prefix="kernel-") as tmp:
        result = kernel.execute_plan(plan.model_dump(mode="json"), Path(tmp) / "out")
        if not result.ok or not result.bodies:
            error = result.error
            request.status = AIRequestStatus.failed
            request.plan_errors = [error.message if error else "kernel produced no bodies"]
            raise JobFailureError(
                error.code if error else "kernel_failed",
                user_safe_kernel_message(
                    error.code if error else "", error.message if error else ""
                ),
                details={
                    "operation_id": error.operation_id if error else None,
                    "operation_type": error.operation_type if error else None,
                    "kernel_message": error.message if error else None,
                },
            )
        ctx.progress(70, "executed")
        expected = set(plan.expected_outputs) or {result.bodies[-1].name}
        main = next((b for b in result.bodies if b.name in expected), result.bodies[-1])
        out_dir = Path(result.output_dir or tmp)
        stl_bytes = (out_dir / main.stl).read_bytes()
        brep_bytes = (out_dir / main.brep).read_bytes()

    model_asset = store_asset(ctx, request, stl_bytes, "stl", {"body": main.name, "kind": "mesh"})
    source_asset = store_asset(
        ctx, request, brep_bytes, "brep", {"body": main.name, "kind": "brep"}
    )
    ctx.progress(85, "uploaded")

    # --- version -----------------------------------------------------------------------------
    bodies = [b.model_dump() for b in result.bodies]
    version = projects.create_version_internal(
        ctx.db,
        project_id=request.project_id,
        parent_version_id=request.project_version_id,
        label=plan.goal[:200],
        provenance={
            "ai_request_id": str(request.id),
            "job_id": str(ctx.job.id),
            "operation": "ai_command",
            "kernel": result.kernel,
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


def store_asset(
    ctx: JobContext, request: AIRequest, data: bytes, format_id: str, metadata: dict[str, Any]
) -> Asset:
    spec = formats.FORMATS[format_id]
    sha256 = hashlib.sha256(data).hexdigest()
    existing = ctx.db.scalar(
        sa.select(Asset).where(Asset.workspace_id == request.workspace_id, Asset.sha256 == sha256)
    )
    if existing is not None:
        return existing
    key = ctx.storage.object_key(request.workspace_id, sha256, spec.extensions[0])
    ctx.storage.put(key, data, spec.mime_types[0])
    asset = Asset(
        workspace_id=request.workspace_id,
        kind=AssetKind.derived,
        sha256=sha256,
        storage_key=key,
        mime=spec.mime_types[0],
        format=format_id,
        byte_size=len(data),
        units=Units.mm,
        metadata_={**metadata, "ai_request_id": str(request.id), "job_id": str(ctx.job.id)},
        created_by=request.user_id,
    )
    ctx.db.add(asset)
    ctx.db.flush()
    return asset


def user_safe_kernel_message(code: str, detail: str) -> str:
    """Translate kernel error codes into something a maker can act on (docs/04)."""
    messages = {
        "fillet_failed": "The rounding radius is too large for those edges; try a smaller radius.",
        "chamfer_failed": "The chamfer distance is too large for those edges; try a smaller value.",
        "boolean_failed": "Two shapes could not be combined; check that they overlap as intended.",
        "no_face_selected": "No flat face points in that direction on this body.",
        "no_edges_selected": "No edges matched the selection.",
        "unknown_body": "The plan refers to a body that does not exist.",
        "invalid_topology": "The result was not a valid solid, so it was discarded.",
        "kernel_timeout": "The geometry took too long to compute; simplify the request.",
        "kernel_unavailable": "The geometry engine is not available on this worker.",
    }
    return messages.get(code, f"The geometry engine could not complete this step ({code}).")
