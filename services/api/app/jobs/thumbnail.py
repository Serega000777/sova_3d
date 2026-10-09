"""Generate and attach the canonical PNG thumbnail for one immutable version."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker.thumbnail import render_png

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset
from app.storage import ObjectNotFoundError

THUMBNAIL_JOB = "render_thumbnail"


@register(THUMBNAIL_JOB)
def handle_thumbnail(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    source_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    source = ctx.db.get(Asset, source_id)
    if version is None or source is None or source.workspace_id != ctx.job.workspace_id:
        raise JobFailureError("input_missing", "version or model asset no longer exists")
    linked_source = ctx.db.scalar(
        sa.select(VersionAsset.asset_id).where(
            VersionAsset.version_id == version.id,
            VersionAsset.asset_id == source.id,
            VersionAsset.role.in_((AssetRole.model, AssetRole.preview, AssetRole.source)),
        )
    )
    if linked_source is None:
        raise JobFailureError("input_missing", "model asset is not attached to this version")
    existing = ctx.db.scalar(
        sa.select(VersionAsset.asset_id)
        .where(
            VersionAsset.version_id == version.id,
            VersionAsset.role == AssetRole.thumbnail,
        )
        .order_by(VersionAsset.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        ctx.progress(100, "already rendered")
        return {"version_id": str(version.id), "asset_id": str(existing)}

    with tempfile.TemporaryDirectory(prefix="thumbnail-") as tmp:
        source_path = Path(tmp) / f"source.{source.format or 'stl'}"
        try:
            with source_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(30, "downloaded")
        try:
            data = render_png(source_path, source.format or "stl")
        except (TypeError, ValueError) as exc:
            raise JobFailureError("thumbnail_failed", str(exc)) from exc
    ctx.progress(75, "rendered")

    thumbnail = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=data,
        format_id="png",
        metadata={
            "operation": THUMBNAIL_JOB,
            "source_asset_id": str(source.id),
            "version_id": str(version.id),
            "width_px": 480,
            "height_px": 320,
        },
        created_by=ctx.job.created_by,
    )
    # Versions are immutable: the first successful canonical preview remains attached.
    ctx.db.add(
        VersionAsset(version_id=version.id, asset_id=thumbnail.id, role=AssetRole.thumbnail)
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=thumbnail.id, role="thumbnail"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {"version_id": str(version.id), "asset_id": str(thumbnail.id)}
