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


def store_extra_parts(
    ctx: JobContext,
    executed: Any,
    *,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID | None,
    tag: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every expected body but the main one becomes a part of its own (F-036): its STL for
    printing and its B-Rep for CAD, listed in the version's provenance as `parts`."""
    parts: list[dict[str, Any]] = []
    bodies = {b.get("name"): b for b in executed.bodies if isinstance(b, dict)}
    for name, (stl, brep) in executed.parts.items():
        if name == executed.main.name:
            continue
        model = store_derived_asset(
            ctx,
            workspace_id=workspace_id,
            data=stl,
            format_id="stl",
            metadata={**tag, "body": name, "kind": "part"},
            created_by=created_by,
        )
        source = store_derived_asset(
            ctx,
            workspace_id=workspace_id,
            data=brep,
            format_id="brep",
            metadata={**tag, "body": name, "kind": "part_brep"},
            created_by=created_by,
        )
        body = bodies.get(name) or {}
        bbox = body.get("bbox_mm") or {}
        parts.append(
            {
                "name": name,
                "asset_id": str(model.id),
                "brep_asset_id": str(source.id),
                "extents_mm": bbox.get("size") if isinstance(bbox, dict) else None,
                "volume_mm3": body.get("volume_mm3"),
            }
        )
    return parts
