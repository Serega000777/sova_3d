"""`reconstruct_scan` job handler (T-079..T-083, F-002, T-250).

Frames out of storage, a reconstruction provider, then the same mesh hygiene every
uploaded model gets: repair (T-083) and an integrity report, with the metric scale
stated as a claim with a confidence (T-082). The session ends `ready` — the user
accepts or retries it (T-084); nothing is written into a project without them.

T-250: right after a non-exterior reconstruction succeeds, the raw mesh is saved as a
durable derived asset and this becomes a pausable checkpoint — if the job is paused
here, a resume skips the whole download/mask/reconstruct pipeline and continues
straight into repair/decimate/texture from that saved mesh. Exterior (COLMAP) jobs do
not get this at all: their texture-projection context is a local, non-serialized
artifact this increment does not persist, so this branch never calls
``pausable_checkpoint`` and only ever uses the plain, non-pausable ``progress()``.
Because a pause request made while an exterior job is already running would otherwise
be silently accepted and then never consumed, ``scanning.pause()`` rejects it with 409
up front instead of letting it do nothing.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import trimesh
from trimesh.visual import ColorVisuals
from worker import exterior, gameready, masking, reconstruction
from worker import repair as mesh_repair
from worker.decimate import QUALITY_WEIGHTS, decimated
from worker.importers.common import as_single_mesh

from app.config import load_settings
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.scanning import ScanFrame, ScanMode, ScanSession, ScanStatus
from app.models.versioning import Asset
from app.services import scanning
from app.services.jobs import JobPausedError
from app.storage import ObjectNotFoundError


def _frames_from_session(frames: list[ScanFrame]) -> list[reconstruction.Frame]:
    """Metadata-only frames for a resumed run: `frame_quality()` only reads pose/quality,
    never `.path`, so there is no need to re-download image bytes just to report on them."""
    return [
        reconstruction.Frame(
            sequence_no=frame.sequence_no,
            path=Path(),
            kind=frame.kind.value,
            pose=dict(frame.pose),
            quality=dict(frame.quality),
        )
        for frame in frames
    ]


def _load_checkpointed_mesh(
    ctx: JobContext, checkpoint: dict[str, Any], work: Path
) -> reconstruction.Reconstruction:
    """Rebuild the `Reconstruction` a paused job saved, from its durable asset."""
    asset_id = uuid.UUID(str(checkpoint["raw_mesh_asset_id"]))
    asset = ctx.db.get(Asset, asset_id)
    if asset is None:
        raise JobFailureError(
            "checkpoint_asset_missing", "the paused reconstruction's saved mesh is gone"
        )
    raw_format = str(checkpoint.get("raw_mesh_format") or asset.format)
    mesh_path = work / f"resumed.{raw_format}"
    try:
        with mesh_path.open("wb") as handle:
            for chunk in ctx.storage.iter_chunks(asset.storage_key):
                handle.write(chunk)
    except ObjectNotFoundError as exc:
        raise JobFailureError("checkpoint_asset_missing", str(exc), retryable=True) from exc
    scale_dict = checkpoint.get("scale") or {}
    scale = reconstruction.ScaleReport(
        applied_mm=float(scale_dict.get("applied_mm", 0.0)),
        source=str(scale_dict.get("source", "assumed")),
        confidence=float(scale_dict.get("confidence", 0.0)),
        warning=scale_dict.get("warning"),
    )
    return reconstruction.Reconstruction(
        mesh_path=mesh_path,
        provider=str(checkpoint.get("provider", "unknown")),
        scale=scale,
        coverage=float(checkpoint.get("coverage", 0.0)),
        details=dict(checkpoint.get("details") or {}),
        format=raw_format,
        texture_context_path=None,
    )


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

    is_exterior = (session.capabilities or {}).get("subject") == "exterior"

    # F-082: a dedicated scanner's fragments are fused; photos go to the configured
    # image-to-3D provider (T-080; `stub` by default, `shap_e` for a real reconstruction).
    provider = (
        "colmap_exterior"
        if is_exterior
        else "fusion"
        if session.mode is ScanMode.scanner
        else load_settings().reconstruction_provider
    )

    checkpoint = dict(ctx.job.checkpoint or {})
    resumed = checkpoint.get("stage") == "reconstructed" and bool(
        checkpoint.get("raw_mesh_asset_id")
    )

    with tempfile.TemporaryDirectory(prefix="scan-") as tmp:
        work = Path(tmp)

        if resumed:
            # T-250: skip frame download, masking, and the reconstruction call entirely —
            # the earlier run already proved this mesh and saved it durably.
            result = _load_checkpointed_mesh(ctx, checkpoint, work)
            inputs = _frames_from_session(frames)
            mask_report = dict(
                checkpoint.get("mask_report")
                or {"mask_applied": False, "reason": "not_requested"}
            )
        else:
            frames_dir = work / "frames"
            frames_dir.mkdir()
            inputs = []
            for frame in frames:
                asset = ctx.db.get(Asset, frame.asset_id)
                if asset is None:
                    raise JobFailureError(
                        "frame_missing", f"frame {frame.sequence_no} has no asset"
                    )
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

            if mask_object:
                try:
                    masked = masking.mask_frames(tuple(inputs), work / "masked")
                except masking.MaskingError as exc:
                    session.status = ScanStatus.failed
                    session.error = {"code": exc.code, "message": exc.message}
                    ctx.db.flush()
                    raise JobFailureError(exc.code, exc.message) from exc
                inputs = list(masked.frames)
                mask_report = masked.report
                ctx.progress(35, "masked")
            else:
                mask_report = {"mask_applied": False, "reason": "not_requested"}

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

            if is_exterior:
                # No durable texture-projection context yet (see module docstring): this
                # method pauses without a resumable checkpoint and a resume starts over.
                ctx.progress(60, "reconstructed")
            else:
                raw_asset = store_derived_asset(
                    ctx,
                    workspace_id=session.workspace_id,
                    data=result.mesh_path.read_bytes(),
                    format_id=result.format,
                    metadata={
                        "scan_session_id": str(session.id),
                        "operation": "reconstruct_scan_checkpoint",
                        "provider": result.provider,
                        "kind": "raw_mesh",
                    },
                    created_by=ctx.job.created_by,
                )
                ctx.db.add(
                    JobArtifact(job_id=ctx.job.id, asset_id=raw_asset.id, role="scan_raw_mesh")
                )
                ctx.db.flush()
                resume_hint = {
                    "raw_mesh_asset_id": str(raw_asset.id),
                    "raw_mesh_format": result.format,
                    "provider": result.provider,
                    "scale": result.scale.to_dict(),
                    "coverage": result.coverage,
                    "details": result.details,
                    "mask_report": mask_report,
                }
                try:
                    ctx.pausable_checkpoint(60, "reconstructed", resume_hint=resume_hint)
                except JobPausedError:
                    session.status = ScanStatus.paused
                    ctx.db.flush()
                    raise

        # --- shared mesh hygiene, whether this mesh is fresh or resumed from a checkpoint ---

        # T-083: a scan mesh is never clean; repair it before anyone sees it.
        colour_source = as_single_mesh(
            trimesh.load(result.mesh_path, force="mesh", process=False)
        )
        repaired_path = work / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(result.mesh_path, result.format, repaired_path)
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
        asset_format = "stl"
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
            if is_exterior:
                if result.texture_context_path is None:
                    texture_report = {
                        "texture_baked": False,
                        "reason": "missing_projection_context",
                    }
                else:
                    textured_path = work / "reconstruction.glb"
                    try:
                        texture_report = exterior.export_projected_texture_glb(
                            final_mesh, result.texture_context_path, texture_size, textured_path
                        )
                    except exterior.ExteriorReconstructionError as exc:
                        texture_report = {"texture_baked": False, "reason": exc.code}
                    if texture_report.get("texture_baked") is True:
                        mesh_bytes = textured_path.read_bytes()
                        asset_format = "glb"
            else:
                transferred = (
                    gameready.transfer_face_colours(final_mesh, colour_source)
                    if colour_source is not None and not colour_source.is_empty
                    else None
                )
                if transferred is None:
                    texture_report = {"texture_baked": False, "reason": "no_color_data"}
                else:
                    final_mesh.visual = ColorVisuals(mesh=final_mesh, face_colors=transferred)
                    textured_path = work / "reconstruction.glb"
                    texture_report = gameready.export_textured_scan_glb(
                        final_mesh, texture_size, textured_path
                    )
                    if texture_report.get("texture_baked") is True:
                        mesh_bytes = textured_path.read_bytes()
                        asset_format = "glb"
        if is_exterior and asset_format != "glb":
            session.status = ScanStatus.failed
            session.error = {
                "code": "texture_projection_failed",
                "message": "the exterior mesh could not retain its projected photo texture",
            }
            ctx.db.flush()
            raise JobFailureError("texture_projection_failed", session.error["message"])
        ctx.progress(85, "decimated")

    asset = store_derived_asset(
        ctx,
        workspace_id=session.workspace_id,
        data=mesh_bytes,
        format_id=asset_format,
        metadata={
            "scan_session_id": str(session.id),
            "operation": "reconstruct_scan",
            "provider": result.provider,
            "kind": "mesh",
            "textured": asset_format == "glb",
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
