"""Async worker job: one uploaded MP4 becomes ordinary JPEG photo assets."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import video

from app import formats
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetKind
from app.storage import ObjectNotFoundError


@register("extract_video_frames")
def handle_extract_video_frames(ctx: JobContext) -> dict[str, Any]:
    source_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    source = ctx.db.get(Asset, source_id)
    if source is None or source.workspace_id != ctx.job.workspace_id:
        raise JobFailureError("asset_not_found", str(source_id))
    if source.format != "mp4" or source.mime != "video/mp4":
        raise JobFailureError(
            "unsupported_format",
            "frame extraction requires an MP4 video asset",
            details={"asset_id": str(source.id), "format": source.format, "mime": source.mime},
        )

    with tempfile.TemporaryDirectory(prefix="extract-video-") as temp_dir:
        input_path = Path(temp_dir) / "source.mp4"
        try:
            with input_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(10, "downloaded")

        outcome = video.extract_frames_in_sandbox(input_path)
        if not outcome.ok or outcome.metadata is None:
            failure = outcome.failure.value if outcome.failure else "video_processing_failed"
            raise JobFailureError(
                failure,
                outcome.message or "video frame extraction failed",
                details={"asset_id": str(source.id)},
            )
        ctx.progress(70, "frames_extracted")

        jpeg_spec = formats.FORMATS["jpeg"]
        asset_ids: list[str] = []
        frame_results: list[dict[str, Any]] = []
        for index, frame in enumerate(outcome.frames, start=1):
            digest = hashlib.sha256(frame.jpeg).hexdigest()
            asset = ctx.db.scalar(
                sa.select(Asset).where(
                    Asset.workspace_id == source.workspace_id,
                    Asset.sha256 == digest,
                )
            )
            if asset is None:
                key = ctx.storage.object_key(source.workspace_id, digest, "jpg")
                ctx.storage.put(key, frame.jpeg, jpeg_spec.mime_types[0])
                asset = Asset(
                    workspace_id=source.workspace_id,
                    kind=AssetKind.derived,
                    sha256=digest,
                    storage_key=key,
                    mime=jpeg_spec.mime_types[0],
                    format=jpeg_spec.id,
                    byte_size=len(frame.jpeg),
                    units=None,
                    metadata_={
                        "derived_from": str(source.id),
                        "operation": "extract_video_frame",
                        "job_id": str(ctx.job.id),
                        "frame_index": index,
                        "timestamp_seconds": round(frame.timestamp_seconds, 6),
                    },
                    created_by=ctx.job.created_by,
                )
                ctx.db.add(asset)
                ctx.db.flush()
            ctx.db.add(
                JobArtifact(
                    job_id=ctx.job.id,
                    asset_id=asset.id,
                    role=f"video_frame_{index}",
                )
            )
            asset_ids.append(str(asset.id))
            frame_results.append(
                {
                    "asset_id": str(asset.id),
                    "timestamp_seconds": round(frame.timestamp_seconds, 6),
                }
            )
        ctx.db.flush()

    ctx.progress(100, "done")
    metadata = outcome.metadata
    return {
        "source_asset_id": str(source.id),
        "asset_ids": asset_ids,
        "frames": frame_results,
        "metadata": {
            "duration_seconds": metadata.duration_seconds,
            "width": metadata.width,
            "height": metadata.height,
            "fps": metadata.fps,
        },
    }
