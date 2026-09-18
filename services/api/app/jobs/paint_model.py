"""`paint_model` job (T-107/T-108, F-034).

Colour is a layer, not a shape: the version's printable mesh is carried over untouched and
the painted result is stored alongside it as a preview the clients render. The strokes stay
in the provenance, so the paint can be replayed onto a later version of the same part.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import paint

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.services import painting, projects
from app.storage import ObjectNotFoundError

PAINTED_FORMAT = "glb"  # carries per-face colour and every client can draw it


@register(painting.PAINT_JOB)
def handle_paint(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    source = ctx.db.get(Asset, asset_id)
    if version is None or source is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")

    payload: dict[str, Any] = {"strokes": ctx.job.input.get("strokes") or []}
    if ctx.job.input.get("base_colour"):
        payload["base_colour"] = ctx.job.input["base_colour"]
    try:
        request = paint.PaintRequest.model_validate(payload)
    except ValueError as exc:
        raise JobFailureError("invalid_paint", str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="paint-") as tmp:
        work = Path(tmp)
        local = work / f"source.{source.format}"
        try:
            with local.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(25, "downloaded")

        output = work / f"painted.{PAINTED_FORMAT}"
        result = paint.run_in_sandbox(
            local, source.format or "stl", request, output, PAINTED_FORMAT
        )
        if not result.ok:
            raise JobFailureError(
                "paint_failed", result.message or "the model could not be painted"
            )
        if result.painted_faces == 0:
            raise JobFailureError(
                "nothing_painted",
                "none of the strokes landed on the model — try drawing on the surface",
                details={"strokes": len(request.strokes)},
            )
        ctx.progress(70, "painted")
        painted_bytes = output.read_bytes()

    painted = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=painted_bytes,
        format_id=PAINTED_FORMAT,
        metadata={
            "operation": painting.PAINT_JOB,
            "source_asset_id": str(source.id),
            "kind": "painted",
            "colours": ",".join(result.colours),
        },
        created_by=ctx.job.created_by,
    )
    ctx.progress(85, "stored")

    report = result.model_dump(mode="json")
    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label=ctx.job.input.get("label") or "Paint",
        provenance={
            "operation": painting.PAINT_JOB,
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            "strokes": request.model_dump(mode="json")["strokes"],
            "base_colour": request.base_colour,
            "paint": report,
        },
        # The shape is unchanged, so the printable model carries over as it is.
        assets={AssetRole.model: source.id, AssetRole.preview: painted.id},
        finalize=True,
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=painted.id, role=AssetRole.preview.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "source_version_id": str(version.id),
        "painted_asset_id": str(painted.id),
        "model_asset_id": str(source.id),
        "paint": report,
    }
