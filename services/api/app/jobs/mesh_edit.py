"""`mesh_edit` job (T-235 / T-236, F-086): the version's mesh goes to the worker, comes back
edited as a new immutable version. A preview only reports; nothing is stored."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from worker import meshedit

from app.jobs.artifacts import store_derived_asset
from app.jobs.import_model import _download
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import assets, projects
from app.services.mesh_edit import MESH_EDIT_JOB

EDITED_FORMAT = "stl"


@register(MESH_EDIT_JOB)
def handle_mesh_edit(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_missing", str(version_id))
    asset = assets.model_asset_of(ctx.db, version)
    if asset is None:
        raise JobFailureError("no_model", "this version has no model to edit")
    try:
        spec = meshedit.EditRequest.model_validate(ctx.job.input.get("request") or {})
    except ValidationError as exc:
        raise JobFailureError("bad_request", str(exc)) from None

    with tempfile.TemporaryDirectory(prefix="meshedit-") as tmp:
        work = Path(tmp)
        source_format = asset.format or EDITED_FORMAT
        source = work / f"source.{source_format}"
        _download(ctx, asset, source)
        ctx.progress(20, "downloaded")
        output = None if spec.preview else work / f"edited.{EDITED_FORMAT}"
        report = meshedit.run_in_sandbox(source, source_format, spec, output)
        if not report.ok:
            raise JobFailureError(
                report.code or "mesh_edit_failed",
                report.message or "the edit could not be applied",
                details={
                    "failed_operation": report.failed_operation,
                    "details": report.details,
                },
            )
        ctx.progress(70, "edited")
        if spec.preview:
            ctx.progress(100, "done")
            return {"preview": True, "report": report.model_dump(mode="json")}
        assert output is not None
        edited_bytes = output.read_bytes()

    edited = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=edited_bytes,
        format_id=EDITED_FORMAT,
        metadata={
            "operation": MESH_EDIT_JOB,
            "source_asset_id": str(asset.id),
            "kind": "mesh_edit",
        },
        created_by=ctx.job.created_by,
    )
    ctx.progress(85, "stored")

    summary = report.model_dump(mode="json", exclude={"preview", "output_path"})
    provenance: dict[str, Any] = {
        "operation": MESH_EDIT_JOB,
        "job_id": str(ctx.job.id),
        "source_version_id": str(version.id),
        "mesh_edit": {
            "operations": spec.model_dump(mode="json")["operations"],
            "report": summary,
            "converted_from_parametric": bool(ctx.job.input.get("converted_from_parametric")),
        },
    }
    labels = ", ".join(op.op.replace("_", " ") for op in spec.operations[:3])
    made = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label=(ctx.job.input.get("label") or f"Mesh edit: {labels}")[:200],
        provenance=provenance,
        # The shape changed, so the old painted preview no longer matches; only the model is new.
        assets={AssetRole.model: edited.id},
        finalize=True,
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=edited.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "model_asset_id": str(edited.id),
        "report": summary,
    }
