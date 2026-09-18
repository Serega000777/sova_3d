"""Shared job helper: content-addressed derived assets."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import sqlalchemy as sa

from app import formats
from app.jobs.runner import JobContext
from app.models.core import Units
from app.models.versioning import Asset, AssetKind


def store_derived_asset(
    ctx: JobContext,
    *,
    workspace_id: uuid.UUID,
    data: bytes,
    format_id: str,
    metadata: dict[str, Any],
    created_by: uuid.UUID | None,
) -> Asset:
    """Upload bytes once per workspace: identical output reuses the existing asset."""
    spec = formats.FORMATS[format_id]
    sha256 = hashlib.sha256(data).hexdigest()
    existing = ctx.db.scalar(
        sa.select(Asset).where(Asset.workspace_id == workspace_id, Asset.sha256 == sha256)
    )
    if existing is not None:
        return existing
    key = ctx.storage.object_key(workspace_id, sha256, spec.extensions[0])
    ctx.storage.put(key, data, spec.mime_types[0])
    asset = Asset(
        workspace_id=workspace_id,
        kind=AssetKind.derived,
        sha256=sha256,
        storage_key=key,
        mime=spec.mime_types[0],
        format=format_id,
        byte_size=len(data),
        units=Units.mm,
        metadata_={**metadata, "job_id": str(ctx.job.id)},
        created_by=created_by,
    )
    ctx.db.add(asset)
    ctx.db.flush()
    return asset
