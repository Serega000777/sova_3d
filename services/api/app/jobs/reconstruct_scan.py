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

import trimesh
from worker import gameready, reconstruction
from worker import repair as mesh_repair
from worker.decimate import QUALITY_WEIGHTS, decimated
from worker.importers.common import as_single_mesh

from app.config import load_settings
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.scanning import ScanMode, ScanSession, ScanStatus
from app.models.versioning import Asset
from app.services import scanning
from app.storage import ObjectNotFoundError


@register(scanning.RECONSTRUCT_JOB)
def handle_reconstruct(ctx: JobContext) -> dict[str, Any]:
    session_id = uuid.UUID(str(ctx.job.input["scan_session_id"]))
    session = ctx.db.get(ScanSession, session_id)
    if session is None:
        raise JobFailureError("scan_session_not_found", str(session_id))
    frames = scanning.list_frames(ctx.db, session)
    required = scanning.min_frames(session)
    if len(frames) < required:
        raise JobFailureError(
            "too_few_frames",
            f"a scan needs at least {required} frame(s)",
            details={"frame_count": len(frames)},
        )

    options = dict(session.processing_options or {})
    method = options.get("method", "photogrammetry")
    quality = options.get("quality", "default")
    texture_size = int(options.get("texture", 2048))
    mask_object = bool(options.get("mask_object", False))

    if method == "gaussian_splat":
        # Gaussian-splat reconstruction is a separate, not-yet-built provider (see the plan's
        # explicit scope cut): refuse loudly rather than silently reconstructing with
        # photogrammetry instead, which would hand back a mesh the user did not ask for.
        session.status = ScanStatus.failed
        session.error = {
            "code": "not_supported_yet",
            "message": "Gaussian-splat reconstruction isn't available yet — choose photogrammetry.",
        }
        ctx.db.flush()
        raise JobFailureError("not_supported_yet", session.error["message"])

    # F-082: a dedicated scanner's fragments are fused; photos go to the configured
    # image-to-3D provider (T-080; `stub` by default, `shap_e` for a real reconstruction).
    provider = (
        "fusion" if session.mode is ScanMode.scanner else load_settings().reconstruction_provider
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
            quality=quality,
        )
        try:
            result = reconstruction.reconstructor_for(provider).reconstruct(scan, work / "out")
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

        # One common decimation step, by quality preset (QUALITY_WEIGHTS mirrors the
        # contracts' QUALITY_PRESETS weights): "raw" (weight 1.0) means no simplification.
        weight = QUALITY_WEIGHTS.get(quality, QUALITY_WEIGHTS["default"])
        decimate_source = (
            repaired_path if outcome.ok and outcome.report is not None else result.mesh_path
        )
        mesh_for_decimation = as_single_mesh(
            trimesh.load(decimate_source, force="mesh", process=False)
        )
        decimate_report: dict[str, Any] = {"quality": quality, "weight": weight}
        if mesh_for_decimation is None or mesh_for_decimation.is_empty:
            texture_report: dict[str, Any] = {"texture_baked": False, "reason": "no_color_data"}
        else:
            native_faces = len(mesh_for_decimation.faces)
            decimate_report["native_faces"] = native_faces
            final_mesh = mesh_for_decimation
            if weight < 1.0:
                target_faces = round(native_faces * weight)
                decimate_report["target_faces"] = target_faces
                final_mesh = decimated(mesh_for_decimation, target_faces)
                decimated_path = work / "decimated.stl"
                final_mesh.export(decimated_path)
                mesh_bytes = decimated_path.read_bytes()
            decimate_report["result_faces"] = len(final_mesh.faces)
            _texture, texture_report = gameready.bake_mesh_texture(final_mesh, texture_size)
        ctx.progress(85, "decimated")

    mask_report = {
        "mask_applied": False,
        "reason": "not_implemented_yet" if mask_object else "not_requested",
    }

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
        "decimate": decimate_report,
        "texture": texture_report,
        "mask": mask_report,
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
