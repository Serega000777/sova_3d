"""`fit_test` job (T-130, F-027): two meshes into the sandbox, one verdict out."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import fit as fitting

from app.api.errors import ValidationFailedError
from app.jobs.print_jobs import _mesh_as_stl
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.engineering import FitTestRecord
from app.models.versioning import Asset, ProjectVersion
from app.services import edits, fit


@register(fit.FIT_JOB)
def handle_fit_test(ctx: JobContext) -> dict[str, Any]:
    version_a = ctx.db.get(ProjectVersion, uuid.UUID(str(ctx.job.input["version_a_id"])))
    version_b = ctx.db.get(ProjectVersion, uuid.UUID(str(ctx.job.input["version_b_id"])))
    asset_a = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["asset_a_id"])))
    asset_b = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["asset_b_id"])))
    if version_a is None or version_b is None or asset_a is None or asset_b is None:
        raise JobFailureError("input_missing", "a version or asset no longer exists")
    placement = fitting.Placement.model_validate(ctx.job.input.get("placement") or {})
    wanted = str(ctx.job.input.get("wanted") or "sliding")
    language: fit.Language = "ru" if ctx.job.input.get("language") == "ru" else "en"

    with tempfile.TemporaryDirectory(prefix="fit-") as tmp_dir:
        tmp = Path(tmp_dir)
        (tmp / "a").mkdir()
        (tmp / "b").mkdir()
        a_path = _mesh_as_stl(ctx, asset_a, tmp / "a")
        b_path = _mesh_as_stl(ctx, asset_b, tmp / "b")
        ctx.progress(25, "downloaded")
        result = fitting.run_in_sandbox(
            a_path, "stl", b_path, "stl", fitting.FitRequest(placement=placement)
        )
    if not result.ok or result.verdict is None:
        raise JobFailureError("fit_failed", result.message or "the parts could not be fitted")
    ctx.progress(75, "fitted")

    measured = result.model_dump(mode="json")
    advice = fit.advise(
        measured,
        operations_a=fit.operations_of(ctx.db, version_a.id),
        b_bbox_mm=result.b_bbox_mm,
        wanted=wanted,  # type: ignore[arg-type]
        material_id=ctx.job.input.get("material_id"),
        language=language,
    )
    if advice.fix is not None:
        try:  # only a fix the edit endpoint would accept as it is
            edits.build_plan(
                ctx.db,
                version=version_a,
                operations=advice.fix["operations"],
                label=advice.fix["label"],
            )
        except ValidationFailedError:
            advice.fix = None

    report = {"measured": measured, "advice": advice.model_dump(mode="json"), "wanted": wanted}
    record = FitTestRecord(
        workspace_id=ctx.job.workspace_id,
        version_a_id=version_a.id,
        version_b_id=version_b.id,
        job_id=ctx.job.id,
        placement=placement.model_dump(mode="json"),
        verdict=result.verdict,
        report=report,
    )
    ctx.db.add(record)
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "fit_test_id": str(record.id),
        "version_a_id": str(version_a.id),
        "version_b_id": str(version_b.id),
        "verdict": result.verdict,
        "report": report,
    }
