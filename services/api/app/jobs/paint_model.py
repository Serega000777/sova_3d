"""`paint_model` job (T-107/T-108, F-034).

Colour is a layer, not a shape: the version's printable mesh is carried over untouched and
the painted result is stored alongside it as a preview the clients render. The strokes stay
in the provenance, so the paint can be replayed onto a later version of the same part.

The painted version also inherits the parent's parametric history — its operation rows,
its BREP and the kernel bodies — so the AI and the manual editor can keep working on it.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import paint

from app.api.errors import ValidationFailedError
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, MeshModifier, Operation
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.services import painting, projects, scenes
from app.storage import ObjectNotFoundError

PAINTED_FORMAT = "glb"  # carries per-face colour and every client can draw it


@register(painting.PAINT_JOB)
def handle_paint(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    source = ctx.db.get(Asset, asset_id)
    scene_node_id = ctx.job.input.get("scene_node_id")
    scene_node_id = str(scene_node_id) if scene_node_id is not None else None
    if version is None or source is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")

    try:
        trusted_strokes = painting.worker_strokes(ctx.job.input.get("strokes") or [])
    except ValidationFailedError as exc:
        raise JobFailureError("invalid_paint", str(exc)) from exc
    payload: dict[str, Any] = {"strokes": trusted_strokes}
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
            "materials": ",".join(result.materials),
        },
        created_by=ctx.job.created_by,
    )
    ctx.progress(85, "stored")

    report = result.model_dump(mode="json")
    parent_provenance = version.provenance or {}
    scene_asset_ids: set[uuid.UUID] | None = None
    if scene_node_id is not None:
        try:
            scene_nodes, scene_asset_ids = scenes.replace_object_asset(
                ctx.db,
                version=version,
                workspace_id=ctx.job.workspace_id,
                node_id=scene_node_id,
                asset_id=painted.id,
            )
        except ValidationFailedError as exc:
            raise JobFailureError("scene_target_invalid", str(exc)) from None
        cleared_material_id: str | None = None
        for node in scene_nodes:
            if str(node.get("id")) == scene_node_id:
                appearance = node.get("appearance")
                if isinstance(appearance, dict):
                    value = appearance.get("catalog_material_id")
                    cleared_material_id = str(value) if value is not None else None
                node["appearance"] = None
                break
        carried = scenes.carried_scene_paint(parent_provenance, scene_nodes)
        carried[scene_node_id] = {
            # The bare local object is retained as replay source; the painted GLB is the node's
            # current immutable asset. Neither id is accepted from the client.
            "source_asset_id": str(source.id),
            "painted_asset_id": str(painted.id),
            "strokes": ctx.job.input.get("strokes") or [],
            "base_colour": request.base_colour,
            "layers": ctx.job.input.get("layers") or [],
            "report": report,
        }
        provenance = {
            **parent_provenance,
            "operation": painting.PAINT_JOB,
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            "scene": {"schema_version": scenes.SCENE_SCHEMA_VERSION, "nodes": scene_nodes},
            "scene_paint": carried,
            "scene_paint_edit": {
                "source_version_id": str(version.id),
                "scene_node_id": scene_node_id,
                "source_asset_id": str(source.id),
                "painted_asset_id": str(painted.id),
                "cleared_material_id": cleared_material_id,
            },
        }
        version_assets = None
    else:
        provenance = {
            "operation": painting.PAINT_JOB,
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            # The one shape every painted version carries (see painting.inherited_paint).
            "paint": {
                # Keep the compact server-validated request as provenance. Expanded PBR snapshots
                # and base64 texture bytes are sandbox inputs only and must never become history.
                "strokes": ctx.job.input.get("strokes") or [],
                "base_colour": request.base_colour,
                "layers": ctx.job.input.get("layers") or [],
                "report": report,
            },
        }
        if parent_provenance.get("bodies"):
            provenance["bodies"] = parent_provenance["bodies"]
        # The shape is unchanged, so every asset but the old preview carries over as it is.
        inherited: dict[AssetRole, uuid.UUID] = {
            link.role: link.asset_id for link in version.assets if link.role != AssetRole.preview
        }
        version_assets = {**inherited, AssetRole.model: source.id, AssetRole.preview: painted.id}
    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label=ctx.job.input.get("label") or "Paint",
        provenance=provenance,
        assets=version_assets,
        finalize=False,
        created_by=ctx.job.created_by,
    )
    # ...and so does the operation log, so the part stays editable after it is painted.
    rows = ctx.db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == version.id)
        .order_by(Operation.sequence_no)
    ).all()
    for row in rows:
        ctx.db.add(
            Operation(
                project_version_id=new_version.id,
                sequence_no=row.sequence_no,
                operation_type=row.operation_type,
                schema_version=row.schema_version,
                params=row.params,
                entity_refs=row.entity_refs,
                enabled=row.enabled,
            )
        )
    modifiers = ctx.db.scalars(
        sa.select(MeshModifier)
        .where(MeshModifier.project_version_id == version.id)
        .order_by(MeshModifier.sequence_no)
    ).all()
    for modifier in modifiers:
        ctx.db.add(
            MeshModifier(
                project_version_id=new_version.id,
                sequence_no=modifier.sequence_no,
                scene_node_id=modifier.scene_node_id,
                modifier_key=modifier.modifier_key,
                modifier_type=modifier.modifier_type,
                enabled=modifier.enabled,
                tolerance_mm=modifier.tolerance_mm,
                params=modifier.params,
            )
        )
    if scene_asset_ids is not None:
        for scene_asset_id in scene_asset_ids:
            projects.attach_asset(
                ctx.db,
                new_version,
                scene_asset_id,
                AssetRole.model,
                workspace_id=ctx.job.workspace_id,
            )
    ctx.db.flush()
    projects.finalize_version(ctx.db, new_version)
    artifact_role = AssetRole.model if scene_node_id is not None else AssetRole.preview
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=painted.id, role=artifact_role.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "source_version_id": str(version.id),
        "painted_asset_id": str(painted.id),
        "model_asset_id": str(painted.id if scene_node_id is not None else source.id),
        "scene_node_id": scene_node_id,
        "paint": {**report, "layers": ctx.job.input.get("layers") or []},
    }
