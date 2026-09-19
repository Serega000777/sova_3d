"""`manual_edit` job handler (T-055/T-038): replay the version's plan with the user's edit.

No planner is involved — the operations come from the inspector, already validated
against the same registry — but everything after that is the AI path exactly:
kernel, content-addressed assets, a new immutable version with its operation log.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from app.jobs.artifacts import store_derived_asset
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
        "bodies": executed.bodies,
    }
    if carried:
        provenance["paint"] = carried.provenance
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
    for index, operation in enumerate(plan.operations, start=1):
        params = operation.model_dump(mode="json")
        ctx.db.add(
            Operation(
                project_version_id=new_version.id,
                sequence_no=index,
                operation_type=operation.type,
                schema_version=1,
                params=params,
                entity_refs=[ref for ref in (getattr(operation, "target", None),) if ref],
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
