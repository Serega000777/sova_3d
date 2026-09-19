"""Carry paint across a geometry edit (T-115, F-034).

The strokes a version carries are the source of truth for its colours, so when the AI or
the inspector changes the shape, the new mesh is painted again with the same strokes. A
stroke that no longer lands anywhere (its surface was cut away) is reported, not hidden.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from worker import paint

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import painting


@dataclass
class CarriedPaint:
    """What the new version gets: a painted preview (when any stroke still lands) + provenance."""

    preview_asset_id: uuid.UUID | None
    provenance: dict[str, Any] = field(default_factory=dict)

    def assets(self) -> dict[AssetRole, uuid.UUID]:
        return {AssetRole.preview: self.preview_asset_id} if self.preview_asset_id else {}


def carry_paint(
    ctx: JobContext,
    parent: ProjectVersion | None,
    stl: bytes,
    *,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID | None,
) -> CarriedPaint | None:
    """Repaint `stl` with the strokes `parent` carries; None when the parent is bare."""
    if parent is None:
        return None
    strokes, base_colour = painting.inherited_paint(parent)
    if not strokes and not base_colour:
        return None
    payload: dict[str, Any] = {"strokes": strokes}
    if base_colour:
        payload["base_colour"] = base_colour
    request = paint.PaintRequest.model_validate(payload)

    with tempfile.TemporaryDirectory(prefix="repaint-") as tmp:
        work = Path(tmp)
        source = work / "model.stl"
        source.write_bytes(stl)
        output = work / "painted.glb"
        result = paint.run_in_sandbox(source, "stl", request, output, "glb")
        painted_bytes = output.read_bytes() if result.ok and result.painted_faces else None

    provenance: dict[str, Any] = {
        "strokes": strokes,
        "base_colour": base_colour,
        "report": result.model_dump(mode="json"),
        "carried_from": str(parent.id),
    }
    if painted_bytes is None:
        # The shape changed under every stroke; the colours are kept for the record only.
        provenance["lost"] = result.message or "no stroke lands on the new shape"
        return CarriedPaint(preview_asset_id=None, provenance=provenance)

    painted = store_derived_asset(
        ctx,
        workspace_id=workspace_id,
        data=painted_bytes,
        format_id="glb",
        metadata={
            "operation": painting.PAINT_JOB,
            "kind": "painted",
            "carried_from": str(parent.id),
            "colours": ",".join(result.colours),
        },
        created_by=created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=painted.id, role=AssetRole.preview.value))
    return CarriedPaint(preview_asset_id=painted.id, provenance=provenance)
