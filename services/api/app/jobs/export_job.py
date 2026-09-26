"""`export` job (F-014/F-076): convert the version's model, validate, attach as an export asset."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import exporters, gameready
from worker import geometry as kernel

from app import formats
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Project, Units
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetKind, AssetRole, ProjectVersion, VersionAsset
from app.services import licensing
from app.storage import ObjectNotFoundError

EXPORT_JOB = "export"


@register(EXPORT_JOB)
def handle_export(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    target = str(ctx.job.input["format"])
    printable = bool(ctx.job.input.get("printable", False))
    game = ctx.job.input.get("game")
    version = ctx.db.get(ProjectVersion, version_id)
    source = ctx.db.get(Asset, asset_id)
    if version is None or source is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")
    cad = target in ("step", "iges")
    if not cad and target not in exporters.SUPPORTED_TARGETS:
        raise JobFailureError("unsupported_target", target)

    with tempfile.TemporaryDirectory(prefix="export-") as tmp_dir:
        tmp = Path(tmp_dir)
        source_path = tmp / f"source.{source.format}"
        try:
            with source_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(20, "downloaded")

        report: dict[str, Any] | None = None
        if cad:
            # F-078: the kernel writes the exact B-Rep; the report is what it wrote
            result = kernel.export_cad(source_path, target, tmp / "cad")
            if not result.ok or not result.file:
                failure = result.error
                raise JobFailureError(
                    failure.code if failure else "export_failed",
                    failure.message if failure else "the kernel could not write the file",
                )
            report = {
                "kernel": result.kernel,
                "bodies": [b.model_dump(mode="json") for b in result.bodies],
            }
            data = (tmp / "cad" / result.file).read_bytes()
            ctx.progress(70, "written")
        elif game is not None:
            # F-077: LODs, UVs, a PBR material and a collider — an engine's asset, not a print
            output_path = tmp / "export.glb"
            built = gameready.run_in_sandbox(
                source_path,
                source.format or "stl",
                gameready.GameRequest.model_validate(game),
                output_path,
            )
            if not built.ok:
                raise JobFailureError("export_failed", built.message or "game export failed")
            report = built.model_dump(mode="json")
            data = output_path.read_bytes()
            ctx.progress(70, "converted")
        else:
            output_path = tmp / f"export.{target}"
            outcome = exporters.export_mesh(
                source_path, source.format or "stl", target, output_path, printable_gate=printable
            )
            ctx.progress(70, "converted")
            report = outcome.report.model_dump(mode="json") if outcome.report else None
            if not outcome.ok:
                if outcome.report is not None:
                    # The integrity/printable gate refused: not a crash, a red result (F-076).
                    raise JobFailureError(
                        "export_blocked",
                        outcome.report.summary,
                        details={"report": report},
                    )
                error = outcome.error
                raise JobFailureError(
                    error.code if error else "export_failed",
                    error.message if error else "conversion failed",
                )
            data = output_path.read_bytes()

    # F-072: the licence and the credit travel with the file's record, chain and all.
    project = ctx.db.get(Project, version.project_id)
    provenance = licensing.permissions(ctx.db, project) if project is not None else None
    spec = formats.FORMATS[target]
    sha256 = hashlib.sha256(data).hexdigest()
    asset = ctx.db.scalar(
        sa.select(Asset).where(Asset.workspace_id == source.workspace_id, Asset.sha256 == sha256)
    )
    if asset is None:
        key = ctx.storage.object_key(source.workspace_id, sha256, spec.extensions[0])
        ctx.storage.put(key, data, spec.mime_types[0])
        asset = Asset(
            workspace_id=source.workspace_id,
            kind=AssetKind.derived,
            sha256=sha256,
            storage_key=key,
            mime=spec.mime_types[0],
            format=target,
            byte_size=len(data),
            units=Units.mm,
            metadata_={
                "derived_from": str(source.id),
                "operation": "export",
                "printable_gate": printable,
                "game_ready": game is not None,
                "integrity": report,
                "job_id": str(ctx.job.id),
                "licence": provenance,
            },
            created_by=ctx.job.created_by,
        )
        ctx.db.add(asset)
        ctx.db.flush()
    # Exports are regenerable, so attaching them to a finalized version is allowed.
    if ctx.db.get(VersionAsset, (version.id, asset.id, AssetRole.export)) is None:
        ctx.db.add(VersionAsset(version_id=version.id, asset_id=asset.id, role=AssetRole.export))
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role="export"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "asset_id": str(asset.id),
        "format": target,
        "byte_size": len(data),
        "printable_gate": printable,
        "report": report,
        "licence": provenance,
    }
