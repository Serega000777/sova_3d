"""`generate_mesh` job handler (F-001/F-075): a description becomes a repaired mesh version."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import trimesh
from worker import exporters, exterior, generate_mesh, reconstruction
from worker import repair as mesh_repair
from worker.importers.common import as_single_mesh
from worker.reconstruction import ReconstructionError

from app.ai.three_d import quality_report_from_repair
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.generation import ThreeDGeneration
from app.models.versioning import Asset, AssetRole
from app.services import projects
from app.services.generation import GENERATE_MESH_JOB
from app.storage import ObjectNotFoundError

NOTE = (
    "Generated from a description by Shap-E: a learned guess at a shape, not a "
    "dimensioned part. Only the longest side is set; check the rest before printing."
)
IMAGE_NOTE = (
    "Generated from one image by Shap-E: visible geometry is inferred and every hidden "
    "surface is a learned guess, not a measured scan. Check the model before printing."
)
MULTIVIEW_NOTE = (
    "Reconstructed from overlapping photos by COLMAP. Camera poses are estimated, the longest "
    "dimension comes from size_mm, and principal axes provide an unmeasured orientation."
)


@register(GENERATE_MESH_JOB)
def handle_generate_mesh(ctx: JobContext) -> dict[str, Any]:
    project_id = uuid.UUID(str(ctx.job.input["project_id"]))
    prompt = str(ctx.job.input.get("prompt") or "")
    size_mm = float(ctx.job.input["size_mm"])
    quality = str(ctx.job.input.get("quality", "fast"))
    generation_request = ctx.job.input.get("generation_request")
    request = generation_request if isinstance(generation_request, dict) else {}
    mode = str(request.get("mode") or "text")
    target_format = str(request.get("target_format") or "stl")
    source_assets: list[Asset] = []

    with tempfile.TemporaryDirectory(prefix="generate-") as tmp:
        work = Path(tmp)
        ctx.progress(5, "generating")
        try:
            if mode == "image":
                image_asset_id = uuid.UUID(str(ctx.job.input["image_asset_id"]))
                source_asset = ctx.db.get(Asset, image_asset_id)
                if source_asset is None or source_asset.workspace_id != ctx.job.workspace_id:
                    raise JobFailureError("asset_missing", str(image_asset_id))
                source_assets.append(source_asset)
                image_path = work / f"source.{source_asset.format or 'image'}"
                try:
                    with image_path.open("wb") as handle:
                        for chunk in ctx.storage.iter_chunks(source_asset.storage_key):
                            handle.write(chunk)
                except ObjectNotFoundError as exc:
                    raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
                result = generate_mesh.generate_from_image(
                    image_path, size_mm, work / "out", quality=quality
                )
                raw_path = result.mesh_path
                raw_format = "stl"
                result_label = result.prompt[:80]
                result_warnings = list(result.warnings)
                result_quality = result.quality
                result_sampling_steps = result.sampling_steps
                result_vertices = result.vertices
                result_faces = result.faces
                result_prompt: str | None = None
                provider_details: dict[str, Any] = {}
                texture_context_path: Path | None = None
            elif mode == "multiview":
                frames: list[reconstruction.Frame] = []
                for sequence_no, raw_id in enumerate(ctx.job.input.get("image_asset_ids") or []):
                    image_asset_id = uuid.UUID(str(raw_id))
                    source_asset = ctx.db.get(Asset, image_asset_id)
                    if source_asset is None or source_asset.workspace_id != ctx.job.workspace_id:
                        raise JobFailureError("asset_missing", str(image_asset_id))
                    source_assets.append(source_asset)
                    image_path = work / f"{sequence_no:05d}.{source_asset.format or 'image'}"
                    try:
                        with image_path.open("wb") as handle:
                            for chunk in ctx.storage.iter_chunks(source_asset.storage_key):
                                handle.write(chunk)
                    except ObjectNotFoundError as exc:
                        raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
                    frames.append(reconstruction.Frame(sequence_no, image_path))
                reconstructed = reconstruction.reconstructor_for("colmap_object").reconstruct(
                    reconstruction.ScanInput(
                        frames=tuple(frames),
                        scale_hint_mm=size_mm,
                        scale_confidence=0.6,
                    ),
                    work / "out",
                )
                raw_path = reconstructed.mesh_path
                raw_format = reconstructed.format
                result_label = "Multi-view object"
                result_warnings = [MULTIVIEW_NOTE]
                result_quality = "photogrammetry"
                result_sampling_steps = 0
                loaded = as_single_mesh(trimesh.load(raw_path, force="mesh", process=False))
                result_vertices = len(loaded.vertices) if loaded is not None else 0
                result_faces = len(loaded.faces) if loaded is not None else 0
                result_prompt = None
                provider_details = reconstructed.to_dict()
                texture_context_path = reconstructed.texture_context_path
            else:
                result = generate_mesh.generate_from_text(
                    prompt, size_mm, work / "out", quality=quality
                )
                raw_path = result.mesh_path
                raw_format = "stl"
                result_label = result.prompt[:80]
                result_warnings = list(result.warnings)
                result_quality = result.quality
                result_sampling_steps = result.sampling_steps
                result_vertices = result.vertices
                result_faces = result.faces
                result_prompt = result.prompt
                provider_details = {}
                texture_context_path = None
        except ReconstructionError as exc:
            raise JobFailureError(exc.code, exc.message) from exc
        ctx.progress(80, "generated")

        raw_bytes = raw_path.read_bytes()
        repaired_path = work / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(raw_path, raw_format, repaired_path)
        if outcome.ok and outcome.report is not None:
            mesh_bytes = repaired_path.read_bytes()
            repair_report: dict[str, Any] = outcome.report.model_dump(mode="json")
        else:
            mesh_bytes = raw_bytes
            error = outcome.error
            repair_report = {
                "ok": False,
                "code": error.code if error else "repair_failed",
                "message": error.message if error else "cleanup did not run",
            }
        integrity_report: dict[str, Any] | None = None
        if target_format == "glb":
            normalized_path = work / "normalized.glb"
            source_path = repaired_path if outcome.ok and outcome.report is not None else raw_path
            if mode == "multiview":
                final_mesh = as_single_mesh(trimesh.load(source_path, force="mesh", process=False))
                if final_mesh is None or texture_context_path is None:
                    raise JobFailureError(
                        "texture_projection_failed",
                        "the multi-view mesh has no usable photo projection context",
                    )
                try:
                    integrity_report = exterior.export_projected_texture_glb(
                        final_mesh,
                        texture_context_path,
                        int(ctx.job.input.get("texture_resolution") or 2048),
                        normalized_path,
                    )
                except exterior.ExteriorReconstructionError as exc:
                    raise JobFailureError(exc.code, exc.message) from exc
            else:
                exported = exporters.export_mesh(source_path, "stl", "glb", normalized_path)
                if not exported.ok:
                    export_error = exported.error
                    raise JobFailureError(
                        export_error.code if export_error else "normalize_failed",
                        (
                            export_error.message
                            if export_error
                            else "the generated mesh could not be normalized"
                        ),
                        details={
                            "report": (
                                exported.report.model_dump(mode="json")
                                if exported.report is not None
                                else None
                            )
                        },
                    )
                integrity_report = (
                    exported.report.model_dump(mode="json") if exported.report is not None else None
                )
            mesh_bytes = normalized_path.read_bytes()
    ctx.progress(90, "cleaned")

    # The runner intentionally commits a failed job. Keep every DB-side artifact, version,
    # lineage link and generation pointer in one savepoint so a late persistence failure
    # cannot turn that failure commit into an orphaned raw Asset row.
    with ctx.db.begin_nested():
        raw_asset = store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=raw_bytes,
            format_id=raw_format,
            metadata={
                "operation": GENERATE_MESH_JOB,
                "provider": str(ctx.job.input.get("provider") or "shap_e"),
                "kind": "raw_mesh",
            },
            created_by=ctx.job.created_by,
        )
        asset = store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=mesh_bytes,
            format_id=target_format,
            metadata={
                "operation": GENERATE_MESH_JOB,
                "provider": str(ctx.job.input.get("provider") or "shap_e"),
                "kind": "normalized_mesh",
                "source_format": raw_format,
                "target_format": target_format,
            },
            created_by=ctx.job.created_by,
        )
        version = projects.create_version_internal(
            ctx.db,
            project_id=project_id,
            label=result_label,
            provenance={
                "operation": GENERATE_MESH_JOB,
                "job_id": str(ctx.job.id),
                "provider": str(ctx.job.input.get("provider") or "shap_e"),
                "mode": mode,
                "prompt": result_prompt,
                "source_asset_ids": [str(item.id) for item in source_assets],
                "size_mm": size_mm,
                "vertices": result_vertices,
                "faces": result_faces,
                "warnings": result_warnings,
                "quality": result_quality,
                "sampling_steps": result_sampling_steps,
                "note": (
                    MULTIVIEW_NOTE
                    if mode == "multiview"
                    else IMAGE_NOTE
                    if mode == "image"
                    else NOTE
                ),
                "provider_details": provider_details,
                "repair": repair_report,
                "normalized_format": target_format,
                "integrity": integrity_report,
            },
            assets={AssetRole.model: asset.id},
            finalize=False,
            created_by=ctx.job.created_by,
        )
        for source_asset in source_assets:
            projects.attach_asset(
                ctx.db,
                version,
                source_asset.id,
                AssetRole.source,
                workspace_id=ctx.job.workspace_id,
            )
        projects.finalize_version(ctx.db, version)
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=raw_asset.id, role="raw_model"))
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
        generation = ctx.db.get(ThreeDGeneration, ctx.job.id)
        quality_report = (
            quality_report_from_repair(repair_report)
            if repair_report.get("ok") is not False and "after" in repair_report
            else None
        )
        if generation is not None:
            generation.raw_asset_id = raw_asset.id
            generation.normalized_asset_id = asset.id
            generation.quality_report = (
                quality_report.model_dump(mode="json") if quality_report is not None else None
            )
        ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "asset_id": str(asset.id),
        "format": target_format,
        "raw_asset_id": str(raw_asset.id),
        "provider_result": {
            "raw_asset_id": str(raw_asset.id),
            "normalized_asset_id": str(asset.id),
            "quality_report": (
                quality_report.model_dump(mode="json") if quality_report is not None else None
            ),
        },
        "warnings": result_warnings,
        "quality": result_quality,
        "sampling_steps": result_sampling_steps,
        "integrity": integrity_report,
    }
