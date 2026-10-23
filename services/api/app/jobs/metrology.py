"""Worker job for rigid CAD ↔ metric scan comparison (F-043)."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import metrology

from app.jobs.print_jobs import _mesh_as_stl
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.versioning import Asset
from app.services.metrology import PHYSICAL_COMPARE_JOB


@register(PHYSICAL_COMPARE_JOB)
def handle_physical_compare(ctx: JobContext) -> dict[str, Any]:
    design = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["design_asset_id"])))
    scan = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["scan_asset_id"])))
    if design is None or scan is None:
        raise JobFailureError("input_missing", "design or scan asset no longer exists")
    with tempfile.TemporaryDirectory(prefix="physical-compare-") as tmp_dir:
        tmp = Path(tmp_dir)
        ctx.progress(10, "loading metric meshes")
        design_dir = tmp / "design"
        scan_dir = tmp / "scan"
        design_dir.mkdir()
        scan_dir.mkdir()
        design_path = _mesh_as_stl(ctx, design, design_dir)
        scan_path = _mesh_as_stl(ctx, scan, scan_dir)
        ctx.progress(35, "registering scan to design")
        report = metrology.compare_in_sandbox(
            design_path,
            scan_path,
            float(ctx.job.input["tolerance_mm"]),
            int(ctx.job.input["samples"]),
        )
    if not report.ok:
        raise JobFailureError("physical_comparison_failed", report.message or "comparison failed")
    ctx.progress(100, "done")
    return {
        "design_version_id": str(ctx.job.input["design_version_id"]),
        "scan_version_id": str(ctx.job.input["scan_version_id"]),
        "scan_session_id": str(ctx.job.input["scan_session_id"]),
        "report": report.model_dump(mode="json"),
    }
