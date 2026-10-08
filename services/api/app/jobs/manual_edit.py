"""`manual_edit` job handler (T-055/T-038): replay the version's plan with the user's edit.

No planner is involved — the operations come from the inspector, already validated
against the same registry — but everything after that is the AI path exactly:
kernel, content-addressed assets, a new immutable version with its operation log.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.jobs.artifacts import store_derived_asset, store_extra_parts
from app.jobs.kernel_exec import run_plan
from app.jobs.paint_carry import carry_paint
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import AssetRole, ProjectVersion
from app.services import edits, projects


@register(edits.EDIT_JOB)
def handle_manual_edit(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_not_found", str(version_id))
    operations: list[dict[str, Any]] = list(ctx.job.input.get("operations") or [])
    label: str | None = ctx.job.input.get("label")
    requested_stack = ctx.job.input.get("operation_stack")
    replace_history = bool(ctx.job.input.get("replace_history"))
    stack: list[edits.StackOperation] | None = None
    if isinstance(requested_stack, list):
        plan, stack = edits.build_stack_plan(
            ctx.db, version=version, items=requested_stack, label=label
        )
    elif replace_history:
        plan = edits.build_replacement_plan(operations=operations, label=label)
    else:
        plan = edits.build_plan(ctx.db, version=version, operations=operations, label=label)
    ctx.progress(20, "planned")

    executed = run_plan(plan)
    ctx.progress(70, "executed")
    main = executed.main

    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=ctx.job.workspace_id,
        created_by=ctx.job.created_by,
    )
    tag = {"source_version_id": str(version.id), "operation": edits.EDIT_JOB}
    model_asset = store(
        data=executed.stl, format_id="stl", metadata={**tag, "body": main.name, "kind": "mesh"}
    )
    source_asset = store(
        data=executed.brep, format_id="brep", metadata={**tag, "body": main.name, "kind": "brep"}
    )
    ctx.progress(85, "uploaded")

    # The paint the version carried goes onto the new shape (T-115).
    carried = None
    if not replace_history:
        carried = carry_paint(
            ctx,
            version,
            executed.stl,
            workspace_id=ctx.job.workspace_id,
            created_by=ctx.job.created_by,
        )
    provenance: dict[str, Any] = {
        "job_id": str(ctx.job.id),
        "source_version_id": str(version.id),
        "operation": edits.EDIT_JOB,
        "kernel": executed.kernel,
        "edit_operations": operations,
        "operation_stack_edit": stack is not None,
        "replaced_history": replace_history,
        "bodies": executed.bodies,
        "expected_outputs": list(plan.expected_outputs),
    }
    if carried:
        provenance["paint"] = carried.provenance
    # a plan with several parts keeps them all (F-036): the lid follows the tray's edits
    if len(executed.parts) > 1:
        provenance["parts"] = store_extra_parts(
            ctx,
            executed,
            workspace_id=ctx.job.workspace_id,
            created_by=ctx.job.created_by,
            tag={"operation": edits.EDIT_JOB, "job_id": str(ctx.job.id)},
        )
    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label=(label or plan.goal)[:200],
        provenance=provenance,
        assets={
            AssetRole.model: model_asset.id,
            AssetRole.source: source_asset.id,
            **(carried.assets() if carried else {}),
        },
        finalize=False,
        created_by=ctx.job.created_by,
    )
    logged_stack = stack
    if logged_stack is None and replace_history:
        logged_stack = [
            edits.StackOperation(operation.model_dump(mode="json"), True)
            for operation in plan.operations
        ]
    elif logged_stack is None:
        previous = edits.operation_stack(ctx.db, version.id)
        active_before = sum(item.enabled for item in previous)
        logged_stack = [
            *previous,
            *[
                edits.StackOperation(operation.model_dump(mode="json"), True)
                for operation in plan.operations[active_before:]
            ],
        ]
    for index, item in enumerate(logged_stack, start=1):
        params = item.operation
        ctx.db.add(
            Operation(
                project_version_id=new_version.id,
                sequence_no=index,
                operation_type=str(params["type"]),
                schema_version=1,
                params=params,
                entity_refs=[
                    str(ref)
                    for ref in (params.get("target"), params.get("tool"), params.get("operation"))
                    if ref
                ],
                enabled=item.enabled,
            )
        )
    ctx.db.flush()
    preview = bool(ctx.job.input.get("preview"))
    if not preview:
        projects.finalize_version(ctx.db, new_version)
    for asset in (model_asset, source_asset):
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "preview": preview,
        "source_version_id": str(version.id),
        "model_asset_id": str(model_asset.id),
        "source_asset_id": str(source_asset.id),
        "plan": plan.model_dump(mode="json"),
        "bodies": executed.bodies,
        "paint": carried.provenance.get("report") if carried else None,
    }
