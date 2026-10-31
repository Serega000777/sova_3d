"""Durable fixed-operation Blender handoff job."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from worker import blender_handoff, exporters

from app.interior_materials import texture_bytes
from app.jobs.artifacts import (
    cleanup_unreferenced_objects,
    lock_derived_asset_objects,
    store_derived_asset,
)
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Project
from app.models.execution import Job, JobArtifact
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset
from app.services import licensing, scene_animations, scenes
from app.services.assets import model_asset_of, preview_asset_of
from app.storage import ObjectNotFoundError


@register("blender_handoff")
def handle_blender_handoff(ctx: JobContext) -> dict[str, Any]:
    if ctx.job.input.get("operation") != "editable_scene":
        raise JobFailureError("operation_invalid", "unsupported Blender handoff operation")
    if ctx.job.input.get("contract_version") != 1:
        raise JobFailureError("contract_invalid", "unsupported Blender handoff contract")
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
        raise JobFailureError("lineage_invalid", "Blender handoff lineage is unavailable")

    with tempfile.TemporaryDirectory(prefix="blender-handoff-") as tmp_dir:
        tmp = Path(tmp_dir)
        source_asset_ids: list[str] = []
        scene_summary: dict[str, Any] | None = None
        expected_animation: exporters.SceneAnimationInput | None = None
        expected_animated_object: str | None = None
        glb_path = tmp / "validated.glb"

        provenance = version.provenance or {}
        has_scene = "scene" in provenance
        if has_scene and not scenes.has_explicit_scene(version):
            raise JobFailureError(
                "scene_schema_unsupported",
                "the scene schema is not supported for Blender handoff",
            )
        if has_scene:
            resolved = scenes.resolve_scene(
                ctx.db,
                version=version,
                workspace_id=project.workspace_id,
            )
            visible = [
                node for node in resolved if node["kind"] == "object" and node["effective_visible"]
            ]
            if not visible:
                raise JobFailureError(
                    "scene_empty", "the scene has no visible geometry for Blender handoff"
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
                appearance = node.get("appearance")
                texture_path: str | None = None
                if isinstance(appearance, dict) and appearance.get("texture_sha256"):
                    texture_sha256 = str(appearance["texture_sha256"])
                    material_path = tmp / f"material-{texture_sha256}.png"
                    if not material_path.exists():
                        material_path.write_bytes(texture_bytes(texture_sha256))
                    texture_path = str(material_path)
                scene_inputs.append(
                    exporters.SceneMeshInput(
                        node_id=str(node["id"]),
                        path=str(source_path),
                        format=asset.format,
                        name=str(node["name"]),
                        world_transform=cast(list[list[float]], node["world_transform"]),
                        appearance=appearance,
                        texture_path=texture_path,
                    )
                )
                source_asset_ids.append(str(asset.id))
            animation_payload = scene_animations.mechanism_animation(
                provenance, {entry.node_id for entry in scene_inputs}
            )
            if animation_payload is not None:
                expected_animation = exporters.SceneAnimationInput.model_validate(animation_payload)
                expected_animated_object = exporters.scene_export_names(scene_inputs)[
                    expected_animation.node_id
                ]
            converted = exporters.export_scene(
                scene_inputs,
                "glb",
                glb_path,
                animation=expected_animation,
            )
            scene_summary = {
                "visible_objects": len(scene_inputs),
                "node_ids": [entry.node_id for entry in scene_inputs],
                "asset_ids": source_asset_ids,
                "transforms_applied": True,
                "appearances_applied": any(entry.appearance is not None for entry in scene_inputs),
                **(
                    {
                        "animations": 1,
                        "animation_kind": f"{expected_animation.kind}_joint",
                        "animated_node_id": expected_animation.node_id,
                    }
                    if expected_animation is not None
                    else {}
                ),
            }
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
        ctx.progress(45, "glb_validated")

        output_path = tmp / "sova-editable.blend"
        packaged = blender_handoff.package_editable_scene(glb_path, output_path)
        if not packaged.ok or packaged.report is None:
            raise JobFailureError(
                packaged.error_code or "blender_failed",
                packaged.message or "Blender produced no handoff artifact",
            )
        glb_sha256 = hashlib.sha256(glb_path.read_bytes()).hexdigest()
        if packaged.report.source_sha256 != glb_sha256:
            raise JobFailureError(
                "source_digest_mismatch",
                "Blender report does not match the validated GLB source",
            )
        if scene_summary is not None and (
            packaged.report.objects != scene_summary["visible_objects"]
            or packaged.report.meshes != scene_summary["visible_objects"]
        ):
            raise JobFailureError(
                "scene_structure_mismatch",
                "Blender did not preserve every visible scene object as a separate mesh object",
                details={
                    "expected_objects": scene_summary["visible_objects"],
                    "reported_objects": packaged.report.objects,
                    "reported_meshes": packaged.report.meshes,
                },
            )
        expected_paths = (
            ["rotation_quaternion"]
            if expected_animation is not None and expected_animation.kind == "revolute"
            else ["location"]
            if expected_animation is not None
            else []
        )
        expected_animated_objects = (
            [expected_animated_object] if expected_animated_object is not None else []
        )
        expected_keyframes = (
            8
            if expected_animation is not None and expected_animation.kind == "revolute"
            else 6
            if expected_animation is not None
            else 0
        )
        if (
            packaged.report.animations != int(expected_animation is not None)
            or packaged.report.animated_objects != expected_animated_objects
            or packaged.report.animation_paths != expected_paths
            or packaged.report.animation_keyframes != expected_keyframes
        ):
            raise JobFailureError(
                "scene_animation_mismatch",
                "Blender did not preserve the exact trusted scene animation",
                details={
                    "expected_animations": int(expected_animation is not None),
                    "reported_animations": packaged.report.animations,
                    "expected_animated_objects": expected_animated_objects,
                    "reported_animated_objects": packaged.report.animated_objects,
                    "expected_paths": expected_paths,
                    "reported_paths": packaged.report.animation_paths,
                    "expected_keyframes": expected_keyframes,
                    "reported_keyframes": packaged.report.animation_keyframes,
                },
            )
        data = output_path.read_bytes()
        if not data.startswith(b"BLENDER"):
            raise JobFailureError("blender_output_invalid", "handoff file has no Blender signature")
        report = packaged.report.model_dump(mode="json")
        if scene_summary is not None:
            report["scene"] = scene_summary
        ctx.progress(80, "blend_packaged")

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
                "operation": "blender_handoff",
                "handoff_operation": "editable_scene",
                "input_glb_sha256": glb_sha256,
                "report": report,
                "licence": licence,
            }
            if len(source_asset_ids) == 1:
                metadata["derived_from"] = source_asset_ids[0]
            if scene_summary is not None:
                metadata["scene"] = scene_summary
            asset = store_derived_asset(
                ctx,
                workspace_id=ctx.job.workspace_id,
                data=data,
                format_id="blend",
                metadata=metadata,
                created_by=ctx.job.created_by,
                created_object_keys=created_object_keys,
            )
            if ctx.db.get(VersionAsset, (version.id, asset.id, AssetRole.export)) is None:
                ctx.db.add(
                    VersionAsset(version_id=version.id, asset_id=asset.id, role=AssetRole.export)
                )
            ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role="blender_handoff"))
            ctx.db.flush()
            ctx.check_still_wanted()
    except Exception:
        cleanup_unreferenced_objects(ctx, created_object_keys)
        raise
    # Do not commit progress after creating records: the runner's jobs.succeed() and final commit
    # must make the asset links, artifact, and terminal job state durable as one transaction.
    return {
        "asset_id": str(asset.id),
        "format": "blend",
        "byte_size": len(data),
        "source_version_id": str(version.id),
        "operation": "editable_scene",
        "report": report,
        "licence": licence,
    }
