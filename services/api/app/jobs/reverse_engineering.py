"""Recognize a mesh, rebuild it through the CAD kernel, and measure the difference."""

from __future__ import annotations

import tempfile
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from worker import features

from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.print_jobs import _mesh_as_stl
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.services import projects, reverse_engineering


@register(reverse_engineering.REVERSE_ENGINEER_JOB)
def handle_reverse_engineer(ctx: JobContext) -> dict[str, Any]:
    version = ctx.db.get(ProjectVersion, uuid.UUID(str(ctx.job.input["version_id"])))
    asset = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["asset_id"])))
    if version is None or asset is None:
        raise JobFailureError("input_missing", "version or model asset no longer exists")
    request = features.FeatureRequest(
        tolerance_mm=float(ctx.job.input.get("tolerance_mm", 0.2)),
        max_levels=int(ctx.job.input.get("max_levels", 64)),
        samples=int(ctx.job.input.get("samples", 3000)),
        threads=bool(ctx.job.input.get("threads", True)),
    )

    with tempfile.TemporaryDirectory(prefix="reverse-engineer-") as tmp_dir:
        tmp = Path(tmp_dir)
        source = _mesh_as_stl(ctx, asset, tmp)
        ctx.progress(15, "recognizing features")
        report = features.recognize_in_sandbox(source, "stl", request)
        if not report.ok or report.reconstruction is None:
            raise JobFailureError(
                "not_reconstructable",
                report.message or "the mesh has no editable prismatic structure",
                details={"warnings": report.warnings},
            )
        try:
            plan = reverse_engineering.plan_from_report(report)
        except Exception as exc:
            raise JobFailureError("reconstruction_plan_failed", str(exc)) from exc
        ctx.progress(45, "rebuilding CAD")
        executed = run_plan(plan)
        rebuilt = tmp / "rebuilt.stl"
        rebuilt.write_bytes(executed.stl)
        comparison = features.deviation_in_sandbox(
            source,
            "stl",
            rebuilt,
            report.reconstruction.frame_transform,
            request.tolerance_mm,
        )
        if not comparison.ok:
            raise JobFailureError("deviation_failed", comparison.message or "comparison failed")
        ctx.progress(75, "measuring deviation")

    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=ctx.job.workspace_id,
        created_by=ctx.job.created_by,
    )
    tag = {
        "operation": reverse_engineering.REVERSE_ENGINEER_JOB,
        "source_version_id": str(version.id),
        "job_id": str(ctx.job.id),
    }
    model_asset = store(data=executed.stl, format_id="stl", metadata={**tag, "kind": "mesh"})
    source_asset = store(data=executed.brep, format_id="brep", metadata={**tag, "kind": "brep"})
    feature_data = report.model_dump(mode="json")
    deviation_data = comparison.model_dump(mode="json")
    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label="Editable CAD reconstruction",
        provenance={
            **tag,
            "kernel": executed.kernel,
            "bodies": executed.bodies,
            "expected_outputs": list(plan.expected_outputs),
            "feature_report": feature_data,
            "deviation": deviation_data,
        },
        assets={AssetRole.model: model_asset.id, AssetRole.source: source_asset.id},
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
    projects.finalize_version(ctx.db, new_version)
    for stored in (model_asset, source_asset):
        ctx.db.add(
            JobArtifact(
                job_id=ctx.job.id,
                asset_id=stored.id,
                role=stored.format or "asset",
            )
        )
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "source_version_id": str(version.id),
        "model_asset_id": str(model_asset.id),
        "source_asset_id": str(source_asset.id),
        "features": feature_data,
        "deviation": deviation_data,
        "plan": plan.model_dump(mode="json"),
    }
