"""Job handlers. Importing this module registers them with the runner."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import repair as mesh_repair

import app.jobs.ai_command  # noqa: F401 — registers `ai_command`
import app.jobs.export_job  # noqa: F401 — registers `export`
import app.jobs.import_model  # noqa: F401 — registers `import_model` / `convert_asset`
import app.jobs.manual_edit  # noqa: F401 — registers `manual_edit`
import app.jobs.paint_model  # noqa: F401 — registers `paint_model`
import app.jobs.print_jobs  # noqa: F401 — registers `analyze_print` / `optimize_print`
import app.jobs.reconstruct_scan  # noqa: F401 — registers `reconstruct_scan`
from app import formats
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetKind, AssetRole, ProjectVersion
from app.services import projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.storage import ObjectNotFoundError


@register("repair")
def handle_repair(ctx: JobContext) -> dict[str, Any]:
    """F-006: repair the version's mesh into a new derived asset + child version."""
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_not_found", str(version_id))
    source_asset = model_asset_of(ctx.db, version)
    if source_asset is None or source_asset.format not in REPAIRABLE_FORMATS:
        raise JobFailureError("no_repairable_asset", "version has no mesh asset to repair")

    with tempfile.TemporaryDirectory(prefix="repair-") as tmp:
        source_path = Path(tmp) / f"source.{source_asset.format}"
        try:
            with source_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source_asset.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(15, "downloaded")

        output_path = Path(tmp) / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(source_path, source_asset.format, output_path)
        if not outcome.ok or outcome.report is None:
            error = outcome.error
            raise JobFailureError(
                error.code if error else "repair_failed",
                error.message if error else "repair produced no output",
                details={"source_asset_id": str(source_asset.id)},
            )
        ctx.progress(70, "repaired")
        repaired_bytes = output_path.read_bytes()

    report = outcome.report.model_dump(mode="json")
    sha256 = hashlib.sha256(repaired_bytes).hexdigest()
    spec = formats.FORMATS["stl"]
    asset = ctx.db.scalar(
        sa.select(Asset).where(
            Asset.workspace_id == source_asset.workspace_id, Asset.sha256 == sha256
        )
    )
    if asset is None:
        key = ctx.storage.object_key(source_asset.workspace_id, sha256, "stl")
        ctx.storage.put(key, repaired_bytes, spec.mime_types[0])
        asset = Asset(
            workspace_id=source_asset.workspace_id,
            kind=AssetKind.derived,
            sha256=sha256,
            storage_key=key,
            mime=spec.mime_types[0],
            format="stl",
            byte_size=len(repaired_bytes),
            units=source_asset.units,
            metadata_={
                "derived_from": str(source_asset.id),
                "operation": "repair",
                "job_id": str(ctx.job.id),
            },
            created_by=ctx.job.created_by,
        )
        ctx.db.add(asset)
        ctx.db.flush()
    ctx.progress(85, "uploaded")

    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label="Repair",
        provenance={
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            "operation": "repair",
            "repair_report": report,
        },
        assets={AssetRole.model: asset.id},
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "asset_id": str(asset.id),
        "source_version_id": str(version.id),
        "report": report,
    }
