"""Durable fixed-operation quad-remesh job."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from worker import exporters, quad_remesh

from app.jobs.artifacts import (
    cleanup_unreferenced_objects,
    lock_derived_asset_objects,
    store_derived_asset,
)
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Project
from app.models.execution import Job, JobArtifact
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset
from app.services import licensing, scenes
from app.services.assets import model_asset_of, preview_asset_of
from app.storage import ObjectNotFoundError


@register("quad_remesh")
def handle_quad_remesh(ctx: JobContext) -> dict[str, Any]:
    if ctx.job.input.get("contract_version") != 1:
        raise JobFailureError("contract_invalid", "unsupported quad-remesh contract")
    target_faces = ctx.job.input.get("target_faces")
    if not isinstance(target_faces, int) or isinstance(target_faces, bool):
        raise JobFailureError("contract_invalid", "quad-remesh target_faces is missing")
    if not 100 <= target_faces <= 100_000:
        raise JobFailureError("contract_invalid", "quad-remesh target_faces is out of bounds")
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    project = ctx.db.get(Project, version.project_id) if version is not None else None
    if (
        version is None
        or project is None
        or version.state.value != "finalized"
        or project.workspace_id != ctx.job.workspace_id
        or ctx.job.project_id != project.id
        or ctx.job.project_version_id != version.id
    ):
        raise JobFailureError("lineage_invalid", "quad-remesh lineage is unavailable")

    with tempfile.TemporaryDirectory(prefix="quad-remesh-") as tmp_dir:
        tmp = Path(tmp_dir)
        source_asset_ids: list[str] = []
        expected_names: set[str] | None = None
        glb_path = tmp / "validated.glb"

        provenance = version.provenance or {}
        has_scene = "scene" in provenance
        if has_scene and not scenes.has_explicit_scene(version):
            raise JobFailureError(
                "scene_schema_unsupported", "the scene schema is not supported for quad-remesh"
            )
        if has_scene:
            resolved = scenes.resolve_scene(
                ctx.db, version=version, workspace_id=project.workspace_id
            )
            visible = [
                node for node in resolved if node["kind"] == "object" and node["effective_visible"]
            ]
            if not visible:
                raise JobFailureError(
                    "scene_empty", "the scene has no visible geometry for quad-remesh"
                )
            downloaded: dict[uuid.UUID, Path] = {}
            scene_inputs: list[exporters.SceneMeshInput] = []
            for node in visible:
                asset_id = uuid.UUID(str(node["resolved_asset_id"]))
                asset = ctx.db.get(Asset, asset_id)
                if (
                    asset is None
                    or asset.workspace_id != ctx.job.workspace_id
                    or asset.format is None
                ):
                    raise JobFailureError(
                        "scene_asset_missing", f"scene asset {asset_id} is unavailable"
                    )
                source_path = downloaded.get(asset.id)
                if source_path is None:
                    source_path = tmp / f"scene-{len(downloaded)}.{asset.format}"
                    try:
                        with source_path.open("wb") as handle:
                            for chunk in ctx.storage.iter_chunks(asset.storage_key):
                                handle.write(chunk)
                    except ObjectNotFoundError as exc:
                        raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
                    downloaded[asset.id] = source_path
                scene_inputs.append(
                    exporters.SceneMeshInput(
                        node_id=str(node["id"]),
                        path=str(source_path),
                        format=asset.format,
                        name=str(node["name"]),
                        world_transform=cast(list[list[float]], node["world_transform"]),
                    )
                )
                source_asset_ids.append(str(asset.id))
            expected_names = set(exporters.scene_export_names(scene_inputs).values())
            converted = exporters.export_scene(scene_inputs, "glb", glb_path)
        else:
            source = preview_asset_of(ctx.db, version) or model_asset_of(ctx.db, version)
            if (
                source is None
                or source.workspace_id != ctx.job.workspace_id
                or source.format is None
            ):
                raise JobFailureError("input_missing", "canonical source asset is unavailable")
            source_path = tmp / f"source.{source.format}"
            try:
                with source_path.open("wb") as handle:
                    for chunk in ctx.storage.iter_chunks(source.storage_key):
                        handle.write(chunk)
            except ObjectNotFoundError as exc:
                raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
            source_asset_ids.append(str(source.id))
            converted = exporters.export_mesh(source_path, source.format, "glb", glb_path)
        ctx.progress(15, "downloaded")

        if not converted.ok:
            error = converted.error
            raise JobFailureError(
                error.code if error else "glb_export_failed",
                error.message if error else "source could not be converted to validated GLB",
                details={
                    "integrity": (
                        converted.report.model_dump(mode="json")
                        if converted.report is not None
                        else None
                    )
                },
            )
        ctx.progress(40, "glb_validated")

        output_path = tmp / "sova-quad-remesh.fbx"
        packaged = quad_remesh.remesh_quads(glb_path, output_path, target_faces)
        if not packaged.ok or packaged.report is None:
            raise JobFailureError(
                packaged.error_code or "blender_failed",
                packaged.message or "Blender produced no quad-remesh artifact",
            )
        glb_sha256 = hashlib.sha256(glb_path.read_bytes()).hexdigest()
        if packaged.report.source_sha256 != glb_sha256:
            raise JobFailureError(
                "source_digest_mismatch",
                "quad-remesh report does not match the validated GLB source",
            )
        if expected_names is not None:
            reported_names = {entry.name for entry in packaged.report.per_object}
            if reported_names != expected_names:
                raise JobFailureError(
                    "scene_structure_mismatch",
                    "quad-remesh did not preserve every visible scene object",
                    details={
                        "expected": sorted(expected_names),
                        "reported": sorted(reported_names),
                    },
                )
        data = output_path.read_bytes()
        if not data.startswith(b"Kaydara"):
            raise JobFailureError(
                "quad_remesh_output_invalid", "quad-remesh file has no FBX signature"
            )
        report = packaged.report.model_dump(mode="json")
        ctx.progress(80, "quad_remesh_packaged")

    licence = licensing.permissions(ctx.db, project) if project is not None else None
    created_object_keys: set[str] = set()
    lock_derived_asset_objects(ctx, workspace_id=ctx.job.workspace_id, payloads=(data,))
    try:
        with ctx.db.begin_nested():
            ctx.db.execute(
                sa.select(Job).where(Job.id == ctx.job.id).with_for_update()
            ).scalar_one()
            ctx.check_still_wanted()
            metadata: dict[str, Any] = {
                "source_asset_ids": source_asset_ids,
                "source_version_id": str(version.id),
                "operation": "quad_remesh",
                "input_glb_sha256": glb_sha256,
                "report": report,
                "licence": licence,
            }
            if len(source_asset_ids) == 1:
                metadata["derived_from"] = source_asset_ids[0]
            asset = store_derived_asset(
                ctx,
                workspace_id=ctx.job.workspace_id,
                data=data,
                format_id="fbx",
                metadata=metadata,
                created_by=ctx.job.created_by,
                created_object_keys=created_object_keys,
            )
            if ctx.db.get(VersionAsset, (version.id, asset.id, AssetRole.export)) is None:
                ctx.db.add(
                    VersionAsset(version_id=version.id, asset_id=asset.id, role=AssetRole.export)
                )
            ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role="quad_remesh"))
            ctx.db.flush()
            ctx.check_still_wanted()
    except Exception:
        cleanup_unreferenced_objects(ctx, created_object_keys)
        raise
    # Do not commit progress after creating records: the runner's jobs.succeed() and final commit
    # must make the asset links, artifact, and terminal job state durable as one transaction.
    return {
        "asset_id": str(asset.id),
        "format": "fbx",
        "byte_size": len(data),
        "source_version_id": str(version.id),
        "target_faces": target_faces,
        "report": report,
        "licence": licence,
    }
