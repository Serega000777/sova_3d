"""`reconstruct_scan` job handler (T-079..T-083, F-002).

Frames out of storage, a reconstruction provider, then the same mesh hygiene every
uploaded model gets: repair (T-083) and an integrity report, with the metric scale
stated as a claim with a confidence (T-082). The session ends `ready` — the user
accepts or retries it (T-084); nothing is written into a project without them.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from worker import reconstruction
from worker import repair as mesh_repair

from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.scanning import ScanSession, ScanStatus
from app.models.versioning import Asset
from app.services import scanning
from app.storage import ObjectNotFoundError

PROVIDER = "stub"  # swappable (T-080); a hosted provider lands as its own adapter


@register(scanning.RECONSTRUCT_JOB)
def handle_reconstruct(ctx: JobContext) -> dict[str, Any]:
    session_id = uuid.UUID(str(ctx.job.input["scan_session_id"]))
    session = ctx.db.get(ScanSession, session_id)
    if session is None:
        raise JobFailureError("scan_session_not_found", str(session_id))
    frames = scanning.list_frames(ctx.db, session)
    if len(frames) < scanning.MIN_FRAMES:
        raise JobFailureError(
            "too_few_frames",
            f"a scan needs at least {scanning.MIN_FRAMES} frames",
            details={"frame_count": len(frames)},
        )

    with tempfile.TemporaryDirectory(prefix="scan-") as tmp:
        work = Path(tmp)
        frames_dir = work / "frames"
        frames_dir.mkdir()
        inputs: list[reconstruction.Frame] = []
        for frame in frames:
            asset = ctx.db.get(Asset, frame.asset_id)
            if asset is None:
                raise JobFailureError("frame_missing", f"frame {frame.sequence_no} has no asset")
            path = frames_dir / f"{frame.sequence_no:05d}_{frame.kind.value}.{asset.format}"
            try:
                with path.open("wb") as handle:
                    for chunk in ctx.storage.iter_chunks(asset.storage_key):
                        handle.write(chunk)
            except ObjectNotFoundError as exc:
                raise JobFailureError("frame_missing", str(exc), retryable=True) from exc
            inputs.append(
                reconstruction.Frame(
                    sequence_no=frame.sequence_no,
                    path=path,
                    kind=frame.kind.value,
                    pose=dict(frame.pose),
                    quality=dict(frame.quality),
                )
            )
        ctx.progress(25, "downloaded")

        scan = reconstruction.ScanInput(
            frames=tuple(inputs),
            mode=session.mode.value,
            scale_hint_mm=float(session.scale_hint_mm) if session.scale_hint_mm else None,
            scale_confidence=(
                float(session.scale_confidence) if session.scale_confidence else None
            ),
            capabilities=dict(session.capabilities),
        )
        try:
            result = reconstruction.reconstructor_for(PROVIDER).reconstruct(scan, work / "out")
        except reconstruction.ReconstructionError as exc:
            session.status = ScanStatus.failed
            session.error = {"code": exc.code, "message": exc.message}
            ctx.db.flush()
            raise JobFailureError(exc.code, exc.message) from exc
        ctx.progress(60, "reconstructed")

        if reconstruction.is_degenerate(result.mesh_path):
            session.status = ScanStatus.failed
            session.error = {
                "code": "empty_reconstruction",
                "message": "the reconstruction produced no solid",
            }
            ctx.db.flush()
            raise JobFailureError(
                "empty_reconstruction", "the reconstruction produced no solid geometry"
            )

        # T-083: a scan mesh is never clean; repair it before anyone sees it.
        repaired_path = work / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(result.mesh_path, "stl", repaired_path)
        if outcome.ok and outcome.report is not None:
            mesh_bytes = repaired_path.read_bytes()
            repair_report = outcome.report.model_dump(mode="json")
        else:
            # Cleanup failing is not fatal — the user still gets the raw scan, with the reason.
            mesh_bytes = result.mesh_path.read_bytes()
            error = outcome.error
            repair_report = {
                "ok": False,
                "code": error.code if error else "repair_failed",
                "message": error.message if error else "cleanup did not run",
            }
        ctx.progress(80, "cleaned")

    asset = store_derived_asset(
        ctx,
        workspace_id=session.workspace_id,
        data=mesh_bytes,
        format_id="stl",
        metadata={
            "scan_session_id": str(session.id),
            "operation": "reconstruct_scan",
            "provider": result.provider,
            "kind": "mesh",
        },
        created_by=ctx.job.created_by,
    )
    report = {
        **result.to_dict(),
        "capture": reconstruction.frame_quality(inputs),
        "repair": repair_report,
    }
    session.mesh_asset_id = asset.id
    session.report = report
    session.status = ScanStatus.ready
    session.error = None
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role="model"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "scan_session_id": str(session.id),
        "status": session.status.value,
        "mesh_asset_id": str(asset.id),
        "report": report,
    }
