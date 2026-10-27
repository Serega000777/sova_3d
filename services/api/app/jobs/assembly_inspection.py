"""Sandboxed world-space envelope inspection for immutable scenes."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import assembly_inspection, sandbox

from app.jobs.import_model import _download
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.versioning import Asset
from app.services.assembly_inspection import ASSEMBLY_INSPECTION_JOB


@register(ASSEMBLY_INSPECTION_JOB)
def handle_assembly_inspection(ctx: JobContext) -> dict[str, Any]:
    raw_components = ctx.job.input.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise JobFailureError("invalid_scene", "assembly inspection components are missing")
    asset_ids = {uuid.UUID(str(item["asset_id"])) for item in raw_components}
    assets = {asset_id: ctx.db.get(Asset, asset_id) for asset_id in asset_ids}
    if any(asset is None for asset in assets.values()):
        raise JobFailureError("asset_missing", "an assembly component asset no longer exists")
    total_bytes = sum(asset.byte_size for asset in assets.values() if asset is not None)
    if total_bytes > sandbox.DEFAULT_LIMITS.max_input_bytes:
        raise JobFailureError(
            "scene_too_large",
            "the unique assembly geometry exceeds the inspection sandbox input limit",
            details={"bytes": total_bytes, "limit": sandbox.DEFAULT_LIMITS.max_input_bytes},
        )

    with tempfile.TemporaryDirectory(prefix="assembly-inspection-") as tmp_dir:
        work = Path(tmp_dir)
        paths: dict[uuid.UUID, Path] = {}
        for asset_id, asset in assets.items():
            assert asset is not None and asset.format is not None
            path = work / f"{asset_id}.{asset.format}"
            _download(ctx, asset, path)
            paths[asset_id] = path
        ctx.progress(35, "downloaded")
        manifest = work / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version_id": str(ctx.job.input["version_id"]),
                    "components": [
                        {
                            "node_id": item["node_id"],
                            "path": str(paths[uuid.UUID(str(item["asset_id"]))]),
                            "format": item["format"],
                            "world_transform": item["world_transform"],
                        }
                        for item in raw_components
                    ],
                }
            )
        )
        result = assembly_inspection.run_in_sandbox(manifest)
    if not result.ok:
        raise JobFailureError(
            "assembly_inspection_failed", result.message or "scene geometry could not be measured"
        )
    ctx.progress(100, "measured")
    return result.model_dump(mode="json")
