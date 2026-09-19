"""`split_model` job (T-142, F-081): the version's mesh goes to the worker, comes back as
parts. Every part and dowel is an asset the user can download and print; the plate with all
of them laid out is the new version's model, so every client shows what was made."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from worker import splitting as cutter

from app.jobs.artifacts import store_derived_asset
from app.jobs.import_model import _download
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import AIRequest, AIRequestStatus, JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import assets, projects
from app.services.splitting import SPLIT_JOB


@register(SPLIT_JOB)
def handle_split(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    request_id = ctx.job.input.get("ai_request_id")
    request = ctx.db.get(AIRequest, uuid.UUID(str(request_id))) if request_id else None
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_missing", str(version_id))
    asset = assets.model_asset_of(ctx.db, version)
    if asset is None:
        raise JobFailureError("no_model", "this version has no model to cut")
    try:
        spec = cutter.SplitRequest.model_validate(ctx.job.input.get("request") or {})
    except ValidationError as exc:
        raise JobFailureError("bad_request", str(exc)) from None

    with tempfile.TemporaryDirectory(prefix="split-") as tmp:
        work = Path(tmp)
        source_format = asset.format or "stl"
        source = work / f"source.{source_format}"
        _download(ctx, asset, source)
        ctx.progress(20, "downloaded")
        out_dir = work / "parts"
        report = cutter.run_in_sandbox(source, source_format, spec, out_dir)
        if not report.ok:
            if request is not None:
                request.status = AIRequestStatus.failed
                request.plan_errors = [report.message]
                ctx.db.flush()
            raise JobFailureError(
                report.code or "split_failed",
                report.message,
                details={
                    "repaired": report.repaired.model_dump(mode="json") if report.repaired else None
                },
            )
        ctx.progress(60, "cut")

        linked: set[tuple[uuid.UUID, str]] = set()

        def store(file: str, kind: str, name: str) -> uuid.UUID:
            # identical parts (two dowels, two symmetric halves) share one content-addressed asset
            made = store_derived_asset(
                ctx,
                workspace_id=ctx.job.workspace_id,
                data=(out_dir / file).read_bytes(),
                format_id="stl",
                metadata={
                    "operation": SPLIT_JOB,
                    "kind": kind,
                    "name": name,
                    "source_version_id": str(version.id),
                },
                created_by=ctx.job.created_by,
            )
            if (made.id, kind) not in linked:
                linked.add((made.id, kind))
                ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=made.id, role=kind))
            return made.id

        parts = [
            {**part.model_dump(mode="json"), "asset_id": str(store(part.file, "part", part.name))}
            for part in report.parts
        ]
        dowels = [
            {**pin.model_dump(mode="json"), "asset_id": str(store(pin.file, "dowel", pin.name))}
            for pin in report.dowels
        ]
        assert report.layout_file is not None
        plate_id = store(report.layout_file, AssetRole.model.value, "layout")
    ctx.progress(85, "stored")

    count = len(parts)
    label = ctx.job.input.get("label") or f"Cut into {count} parts"
    preview = bool(ctx.job.input.get("preview"))
    split: dict[str, Any] = {
        "request": spec.model_dump(mode="json"),
        "planes": [plane.model_dump(mode="json") for plane in report.planes],
        "parts": parts,
        "dowels": dowels,
        "layout_extents_mm": report.layout_extents_mm,
        "input_volume_mm3": report.input_volume_mm3,
        "warnings": report.warnings,
        "repaired": report.repaired.model_dump(mode="json") if report.repaired else None,
    }
    made = projects.create_version_internal(
        ctx.db,
        project_id=project_id,
        parent_version_id=version.id,
        label=label[:200],
        provenance={
            "operation": SPLIT_JOB,
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            "split": split,
        },
        assets={AssetRole.model: plate_id},
        finalize=not preview,
        created_by=ctx.job.created_by,
    )
    if request is not None:
        request.status = AIRequestStatus.executed
        request.result_version_id = made.id
        request.output_plan = {"split": {k: v for k, v in split.items() if k != "repaired"}}
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "preview": preview,
        "model_asset_id": str(plate_id),
        "parts": parts,
        "dowels": dowels,
        "warnings": report.warnings,
        "repaired": report.repaired.changed if report.repaired else False,
        "ai_request_id": str(request.id) if request else None,
        "status": "executed",
    }
