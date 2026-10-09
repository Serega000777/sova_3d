"""Execute an exact facade plan and save it as an immutable child version."""

from __future__ import annotations

import tempfile
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError
from worker.facade_materials import (
    Assignment,
    FacadeMaterialRequest,
    Opening,
    run_in_sandbox,
)

from app.engineering.facade import FacadeRequest, opening_key, surface_records
from app.jobs.artifacts import store_derived_asset
from app.jobs.kernel_exec import run_plan
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact, Operation
from app.models.versioning import AssetRole, ProjectVersion
from app.services import projects

FACADE_ADAPTER = TypeAdapter(FacadeRequest)


@register("edit_facade")
def handle_facade(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    source = ctx.db.get(ProjectVersion, version_id)
    if source is None or source.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    try:
        request = FacadeRequest(**dict(ctx.job.input["request"]))
        plan = request.build()
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise JobFailureError("invalid_facade", str(exc)) from exc
    ctx.progress(15, "planned")
    executed = run_plan(plan)
    ctx.progress(70, "executed")
    store = partial(
        store_derived_asset,
        ctx,
        workspace_id=ctx.job.workspace_id,
        created_by=ctx.job.created_by,
    )
    tag = {"operation": "edit_facade", "job_id": str(ctx.job.id)}
    model_asset = store(data=executed.stl, format_id="stl", metadata={**tag, "kind": "mesh"})
    source_asset = store(data=executed.brep, format_id="brep", metadata={**tag, "kind": "brep"})
    house = {
        "length_mm": request.length_mm,
        "width_mm": request.width_mm,
        "floor_height_mm": request.floor_height_mm,
        "floors": request.floors,
        "shape": "rectangle",
    }
    request_data = FACADE_ADAPTER.dump_python(request, mode="json")
    dropped = list(ctx.job.input.get("dropped_surface_assignments") or [])
    preview_asset = None
    material_report: dict[str, Any] = {
        "applied_surface_keys": [],
        "dropped_surface_keys": dropped,
    }
    if request.surface_assignments:
        material_request = FacadeMaterialRequest(
            length_mm=request.length_mm,
            width_mm=request.width_mm,
            height_mm=request.floor_height_mm * request.floors,
            wall_thickness_mm=request.wall_thickness_mm,
            roof=request.roof,
            openings=[
                Opening(
                    opening_id=opening_key(opening, index),
                    kind=opening.kind,
                    side=opening.side,
                    center_mm=opening.center_mm,
                    width_mm=opening.width_mm,
                    height_mm=opening.height_mm,
                    sill_mm=opening.sill_mm,
                )
                for index, opening in enumerate(request.openings)
            ],
            assignments=[
                Assignment(
                    surface_key=item.surface_key,
                    colour=item.colour,
                    material_id=item.material_id,
                )
                for item in request.surface_assignments
            ],
        )
        with tempfile.TemporaryDirectory(prefix="facade-materials-") as tmp:
            source_path = Path(tmp) / "facade.stl"
            preview_path = Path(tmp) / "facade.glb"
            source_path.write_bytes(executed.stl)
            result = run_in_sandbox(source_path, material_request, preview_path)
            if not result.ok:
                raise JobFailureError(
                    "facade_material_failed", result.message or "material preview failed"
                )
            if result.unused_surface_keys:
                raise JobFailureError(
                    "facade_surface_missing",
                    "semantic facade surfaces no longer match the exact output",
                    details={"surface_keys": result.unused_surface_keys},
                )
            preview_asset = store(
                data=preview_path.read_bytes(),
                format_id="glb",
                metadata={**tag, "kind": "facade_material_preview"},
            )
            material_report = {
                **result.model_dump(mode="json"),
                "dropped_surface_keys": dropped,
            }
    provenance = {
        **(source.provenance or {}),
        **tag,
        "kernel": executed.kernel,
        "plan_goal": plan.goal,
        "bodies": executed.bodies,
        "facade": {
            "house": house,
            "request": request_data,
            "source_version_id": str(source.id),
            "surfaces": surface_records(request),
            "material_report": material_report,
        },
    }
    version = projects.create_version_internal(
        ctx.db,
        project_id=source.project_id,
        parent_version_id=source.id,
        label="Facade edit",
        provenance=provenance,
        assets={
            AssetRole.model: model_asset.id,
            AssetRole.source: source_asset.id,
            **({AssetRole.preview: preview_asset.id} if preview_asset is not None else {}),
        },
        finalize=False,
        created_by=ctx.job.created_by,
    )
    for index, operation in enumerate(plan.operations, start=1):
        params = operation.model_dump(mode="json")
        ctx.db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=index,
                operation_type=operation.type,
                schema_version=1,
                params=params,
                entity_refs=[ref for ref in (getattr(operation, "target", None),) if ref],
            )
        )
    ctx.db.flush()
    projects.finalize_version(ctx.db, version)
    for asset in (model_asset, source_asset, preview_asset):
        if asset is None:
            continue
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=asset.format or "asset"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(version.id),
        "source_version_id": str(source.id),
        "model_asset_id": str(model_asset.id),
        "source_asset_id": str(source_asset.id),
        "opening_count": len(request.openings),
        "roof": request.roof,
        "surface_materials": material_report,
    }
