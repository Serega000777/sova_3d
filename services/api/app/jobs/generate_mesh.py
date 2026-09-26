"""`generate_mesh` job handler (F-001/F-075): a description becomes a repaired mesh version."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import generate_mesh
from worker import repair as mesh_repair
from worker.reconstruction import ReconstructionError

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole
from app.services import projects
from app.services.generation import GENERATE_MESH_JOB

NOTE = (
    "Generated from a description by Shap-E: a learned guess at a shape, not a "
    "dimensioned part. Only the longest side is set; check the rest before printing."
)


@register(GENERATE_MESH_JOB)
def handle_generate_mesh(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    prompt = str(ctx.job.input["prompt"])
    size_mm = float(ctx.job.input["size_mm"])

    with tempfile.TemporaryDirectory(prefix="generate-") as tmp:
        work = Path(tmp)
        ctx.progress(5, "generating")
        try:
            result = generate_mesh.generate_from_text(prompt, size_mm, work / "out")
        except ReconstructionError as exc:
            raise JobFailureError(exc.code, exc.message) from exc
        ctx.progress(80, "generated")

        repaired_path = work / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(result.mesh_path, "stl", repaired_path)
        if outcome.ok and outcome.report is not None:
            mesh_bytes = repaired_path.read_bytes()
            repair_report: dict[str, Any] = outcome.report.model_dump(mode="json")
        else:
            mesh_bytes = result.mesh_path.read_bytes()
            error = outcome.error
            repair_report = {
                "ok": False,
                "code": error.code if error else "repair_failed",
                "message": error.message if error else "cleanup did not run",
            }
    ctx.progress(90, "cleaned")

    asset = store_derived_asset(
        ctx,
        workspace_id=ctx.job.workspace_id,
        data=mesh_bytes,
        format_id="stl",
        metadata={"operation": GENERATE_MESH_JOB, "provider": "shap_e", "kind": "mesh"},
        created_by=ctx.job.created_by,
    )
    version = projects.create_version_internal(
        ctx.db,
        project_id=project_id,
        label=result.prompt[:80],
        provenance={
            "operation": GENERATE_MESH_JOB,
            "job_id": str(ctx.job.id),
            "provider": "shap_e",
            "prompt": result.prompt,
            "size_mm": result.size_mm,
            "vertices": result.vertices,
            "faces": result.faces,
            "warnings": list(result.warnings),
            "note": NOTE,
            "repair": repair_report,
        },
        assets={AssetRole.model: asset.id},
        finalize=True,
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "asset_id": str(asset.id),
        "warnings": list(result.warnings),
    }
