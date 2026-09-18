"""`import_model` and `convert_asset` jobs (T-110/T-112, F-014/F-015).

Bringing a file in and taking one out are the same operation seen from two sides, so they
share one implementation: parse the upload in the sandbox (or the OCCT kernel for STEP and
IGES), convert it, and check what the conversion cost (F-015). Importing keeps both files —
the original the user gave us and the mesh everything downstream renders — because the
original is the only thing we can never regenerate.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import exporters
from worker.importers import CAD_FORMATS
from worker.importers.cad import import_cad

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetRole
from app.services import projects
from app.services.imports import CONVERT_JOB, IMPORT_JOB
from app.storage import ObjectNotFoundError

VIEWABLE = "stl"  # what the clients render; the original is kept alongside it


def _download(ctx: JobContext, asset: Asset, target: Path) -> None:
    try:
        with target.open("wb") as handle:
            for chunk in ctx.storage.iter_chunks(asset.storage_key):
                handle.write(chunk)
    except ObjectNotFoundError as exc:
        raise JobFailureError("asset_missing", str(exc), retryable=True) from exc


def _convert(ctx: JobContext, asset: Asset, target_format: str, work: Path) -> tuple[bytes, Any]:
    """Source bytes in, target bytes and an integrity report out."""
    source_format = asset.format or "stl"
    source = work / f"source.{source_format}"
    _download(ctx, asset, source)
    ctx.progress(30, "downloaded")

    if source_format in CAD_FORMATS:
        # B-Rep: the kernel reads it and writes the mesh the platform stores.
        out_dir = work / "cad"
        result = import_cad(source, source_format, out_dir=out_dir)
        if not result.ok or result.metadata is None:
            error = result.error
            raise JobFailureError(
                error.code if error else "cad_unreadable",
                error.message if error else "the file could not be read",
            )
        meshes = sorted(out_dir.glob("*.stl"))
        if not meshes:
            raise JobFailureError("cad_empty", "the file contains no geometry")
        source = meshes[0]
        source_format = "stl"
        if target_format == "stl":
            return source.read_bytes(), result.metadata.model_dump(mode="json")

    if source_format == target_format:
        return source.read_bytes(), None

    output = work / f"target.{target_format}"
    outcome = exporters.export_mesh(source, source_format, target_format, output)
    if not outcome.ok:
        error = outcome.error
        raise JobFailureError(
            error.code if error else "convert_failed",
            error.message if error else "the file could not be converted",
            details={"report": outcome.report.model_dump(mode="json") if outcome.report else None},
        )
    report = outcome.report.model_dump(mode="json") if outcome.report else None
    return output.read_bytes(), report


@register(IMPORT_JOB)
def handle_import(ctx: JobContext) -> dict[str, Any]:
    """T-110: an uploaded file becomes a version the clients can open."""
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    label = ctx.job.input.get("label")
    asset = ctx.db.get(Asset, asset_id)
    if asset is None:
        raise JobFailureError("asset_missing", str(asset_id))

    with tempfile.TemporaryDirectory(prefix="import-") as tmp:
        mesh_bytes, report = _convert(ctx, asset, VIEWABLE, Path(tmp))
    ctx.progress(70, "converted")

    same = asset.format == VIEWABLE
    model = (
        asset
        if same
        else store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=mesh_bytes,
            format_id=VIEWABLE,
            metadata={
                "operation": IMPORT_JOB,
                "source_asset_id": str(asset.id),
                "source_format": asset.format,
                "kind": "mesh",
            },
            created_by=ctx.job.created_by,
        )
    )
    ctx.progress(85, "stored")

    assets = {AssetRole.model: model.id}
    if not same:
        assets[AssetRole.source] = asset.id  # the file the user gave us, untouched
    version = projects.create_version_internal(
        ctx.db,
        project_id=project_id,
        label=label or (asset.metadata_ or {}).get("filename") or "Imported model",
        provenance={
            "operation": IMPORT_JOB,
            "job_id": str(ctx.job.id),
            "source_asset_id": str(asset.id),
            "source_format": asset.format,
            "integrity": report,
        },
        assets=assets,
        finalize=True,
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=model.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "asset_id": str(model.id),
        "source_asset_id": str(asset.id),
        "source_format": asset.format,
        "integrity": report,
    }


@register(CONVERT_JOB)
def handle_convert(ctx: JobContext) -> dict[str, Any]:
    """T-112: convert a file to another format and say what the conversion cost."""
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    target_format = str(ctx.job.input["format"])
    asset = ctx.db.get(Asset, asset_id)
    if asset is None:
        raise JobFailureError("asset_missing", str(asset_id))
    if target_format not in exporters.SUPPORTED_TARGETS:
        raise JobFailureError(
            "unsupported_target",
            f"cannot write {target_format}",
            details={"supported": sorted(exporters.SUPPORTED_TARGETS)},
        )

    with tempfile.TemporaryDirectory(prefix="convert-") as tmp:
        data, report = _convert(ctx, asset, target_format, Path(tmp))
    ctx.progress(80, "converted")

    converted = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=data,
        format_id=target_format,
        metadata={
            "operation": CONVERT_JOB,
            "source_asset_id": str(asset.id),
            "source_format": asset.format,
            "kind": "mesh",
        },
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=converted.id, role=AssetRole.export.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "asset_id": str(converted.id),
        "format": target_format,
        "source_asset_id": str(asset.id),
        "source_format": asset.format,
        "byte_size": len(data),
        "integrity": report,
    }
