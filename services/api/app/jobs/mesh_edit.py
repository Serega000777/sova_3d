"""`mesh_edit` job (T-235 / T-236, F-086): the version's mesh goes to the worker, comes back
edited as a new immutable version. A preview only reports; nothing is stored."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from worker import meshedit

from app.api.errors import ValidationFailedError
from app.jobs.artifacts import store_derived_asset
from app.jobs.import_model import _download
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, MeshModifier
from app.models.versioning import AssetRole, ProjectVersion
from app.services import assets, projects
from app.services import mesh_edit as mesh_edit_service
from app.services.mesh_edit import MESH_EDIT_JOB

EDITED_FORMAT = "stl"


@register(MESH_EDIT_JOB)
def handle_mesh_edit(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_missing", str(version_id))
    requested_stack = ctx.job.input.get("modifier_stack")
    stack: list[mesh_edit_service.StackModifier] | None = None
    if isinstance(requested_stack, list):
        try:
            stack = mesh_edit_service.build_modifier_stack(
                ctx.db, version=version, items=requested_stack
            )
            _, asset = mesh_edit_service.modifier_stack_base(
                ctx.db, version, workspace_id=ctx.job.workspace_id
            )
        except ValidationFailedError as exc:
            raise JobFailureError("bad_modifier_stack", str(exc)) from None
        spec = None
    else:
        current_asset = assets.model_asset_of(ctx.db, version)
        if current_asset is None:
            raise JobFailureError("no_model", "this version has no model to edit")
        asset = current_asset
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
        if stack is not None:
            active = [item for item in stack if item.enabled]
            reports: list[dict[str, Any]] = []
            current = source
            current_format = source_format
            for index, item in enumerate(active, start=1):
                try:
                    step = meshedit.EditRequest.model_validate(
                        {
                            "operations": [item.operation],
                            "tolerance_mm": item.tolerance_mm,
                        }
                    )
                except ValidationError as exc:
                    raise JobFailureError("bad_modifier_stack", str(exc)) from None
                output = work / f"modifier-{index}.{EDITED_FORMAT}"
                report = meshedit.run_in_sandbox(current, current_format, step, output)
                if not report.ok:
                    raise JobFailureError(
                        report.code or "mesh_modifier_failed",
                        report.message or "the mesh modifier could not be replayed",
                        details={
                            "modifier_id": item.key,
                            "failed_operation": report.failed_operation,
                            "details": report.details,
                        },
                    )
                reports.append(report.model_dump(mode="json", exclude={"output_path"}))
                current, current_format = output, EDITED_FORMAT
            edited_bytes = current.read_bytes()
            summary: dict[str, Any] = {
                "ok": True,
                "steps": reports,
                "before": reports[0].get("before") if reports else None,
                "after": reports[-1].get("after") if reports else None,
                "warnings": [warning for item in reports for warning in item.get("warnings", [])],
                "repairs": [repair for item in reports for repair in item.get("repairs", [])],
            }
            active_operations = [item.operation for item in active]
            preview = False
        else:
            assert spec is not None
            direct_output = None if spec.preview else work / f"edited.{EDITED_FORMAT}"
            report = meshedit.run_in_sandbox(source, source_format, spec, direct_output)
            if not report.ok:
                raise JobFailureError(
                    report.code or "mesh_edit_failed",
                    report.message or "the edit could not be applied",
                    details={
                        "failed_operation": report.failed_operation,
                        "details": report.details,
                    },
                )
            summary = report.model_dump(mode="json", exclude={"preview", "output_path"})
            active_operations = spec.model_dump(mode="json")["operations"]
            preview = spec.preview
            edited_bytes = b"" if direct_output is None else direct_output.read_bytes()
        ctx.progress(70, "edited")
        if preview:
            ctx.progress(100, "done")
            return {"preview": True, "report": report.model_dump(mode="json")}

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

    previous = mesh_edit_service.modifier_stack(ctx.db, version.id)
    if stack is None:
        stack = list(previous)
        assert spec is not None
        for operation in spec.model_dump(mode="json")["operations"]:
            key = mesh_edit_service.next_modifier_key(stack)
            stack.append(
                mesh_edit_service.StackModifier(
                    key=key,
                    operation=operation,
                    enabled=True,
                    tolerance_mm=spec.tolerance_mm,
                )
            )
    if previous:
        base_version_id, base_asset = mesh_edit_service.modifier_stack_base(
            ctx.db, version, workspace_id=ctx.job.workspace_id
        )
    else:
        base_version_id, base_asset = version.id, asset
    provenance: dict[str, Any] = {
        "operation": MESH_EDIT_JOB,
        "job_id": str(ctx.job.id),
        "source_version_id": str(version.id),
        "mesh_edit": {
            "operations": active_operations,
            "report": summary,
            "converted_from_parametric": bool(ctx.job.input.get("converted_from_parametric")),
        },
        "mesh_modifier_stack": {
            "base_version_id": str(base_version_id),
            "base_asset_id": str(base_asset.id),
            "rebuild": requested_stack is not None,
        },
    }
    labels = ", ".join(str(op["op"]).replace("_", " ") for op in active_operations[:3])
    made = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label=(ctx.job.input.get("label") or f"Mesh edit: {labels}")[:200],
        provenance=provenance,
        # The shape changed, so the old painted preview no longer matches; only the model is new.
        assets={AssetRole.model: edited.id},
        finalize=False,
        created_by=ctx.job.created_by,
    )
    for index, item in enumerate(stack, start=1):
        ctx.db.add(
            MeshModifier(
                project_version_id=made.id,
                sequence_no=index,
                modifier_key=item.key,
                modifier_type=str(item.operation["op"]),
                enabled=item.enabled,
                tolerance_mm=item.tolerance_mm,
                params=item.operation,
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, made)
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=edited.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "model_asset_id": str(edited.id),
        "report": summary,
        "modifier_count": len(stack),
    }
