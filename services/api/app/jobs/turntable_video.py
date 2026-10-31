"""Render and store one deterministic turntable MP4 for an immutable 3D version."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset
from app.storage import ObjectNotFoundError

TURNTABLE_VIDEO_JOB = "render_turntable_video"
TURNTABLE_VIDEO_FORMATS = frozenset(
    {
        "stl",
        "obj",
        "ply",
        "glb",
        "gltf",
        "3mf",
        "dae",
        "usdz",
        "x3d",
        "x3dv",
        "wrl",
        "fbx",
        "abc",
    }
)


@register(TURNTABLE_VIDEO_JOB)
def handle_turntable_video(ctx: JobContext) -> dict[str, Any]:
    # Keep the API image compute-free: only the worker target imports the renderer and ffmpeg.
    from worker.turntable_video import render_turntable_mp4

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
    if source.format not in TURNTABLE_VIDEO_FORMATS:
        raise JobFailureError("unsupported_format", "model asset cannot be rendered to video")

    with tempfile.TemporaryDirectory(prefix="turntable-video-") as tmp:
        source_path = Path(tmp) / f"source.{source.format}"
        try:
            with source_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(20, "downloaded")
        try:
            rendered = render_turntable_mp4(source_path, source.format)
        except (TypeError, ValueError) as exc:
            raise JobFailureError("video_render_failed", str(exc)) from exc
        ctx.progress(80, "rendered")

    video = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=rendered.mp4,
        format_id="mp4",
        metadata={
            "operation": TURNTABLE_VIDEO_JOB,
            "source_asset_id": str(source.id),
            "version_id": str(version.id),
            "width_px": rendered.width,
            "height_px": rendered.height,
            "fps": rendered.fps,
            "frame_count": rendered.frame_count,
            "duration_seconds": rendered.duration_seconds,
            "render_kind": "deterministic_turntable",
        },
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=video.id, role="turntable_video"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "source_asset_id": str(source.id),
        "asset_id": str(video.id),
        "metadata": {
            "width": rendered.width,
            "height": rendered.height,
            "fps": rendered.fps,
            "frame_count": rendered.frame_count,
            "duration_seconds": rendered.duration_seconds,
            "render_kind": "deterministic_turntable",
        },
    }
