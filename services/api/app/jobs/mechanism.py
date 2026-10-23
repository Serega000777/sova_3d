"""Build real mechanism parts (hinge, sliding lid) and store their joint contracts."""

from __future__ import annotations

import uuid
from typing import Any

from worker.mechanisms import build_hinged_lid, build_sliding_lid, sliding_lid_layout

from app.api.mechanisms import (
    HINGED_LID_JOB,
    SLIDING_LID_JOB,
    HingedLidBody,
    SlidingLidBody,
)
from app.jobs.artifacts import store_derived_asset
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import AssetRole, ProjectVersion
from app.services import scenes


def _object(node_id: str, name: str, asset_id: uuid.UUID, parent_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": name,
        "kind": "object",
        "parent_id": parent_id,
        "visible": True,
        "transform": [row[:] for row in scenes.IDENTITY],
        "asset_id": str(asset_id),
        "instance_of": None,
        "footprint_mm": None,
    }


@register(HINGED_LID_JOB)
def handle_hinged_lid(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None or version.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    try:
        spec = HingedLidBody.model_validate(ctx.job.input.get("spec"))
        payloads = build_hinged_lid(**spec.model_dump(exclude={"max_angle_deg"}))
    except (TypeError, ValueError) as exc:
        raise JobFailureError("invalid_mechanism", str(exc)) from exc
    ctx.progress(35, "built mechanism parts")

    assets: dict[str, Any] = {}
    for role, payload in payloads.items():
        asset = store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=payload,
            format_id="stl",
            metadata={
                "operation": HINGED_LID_JOB,
                "mechanism_kind": "hinged_lid",
                "mechanism_role": role,
            },
            created_by=ctx.job.created_by,
        )
        assets[role] = asset
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.progress(65, "stored mechanism parts")

    suffix = uuid.uuid4().hex[:10]
    root_id = f"hinge_{suffix}"
    base_id = f"hinge_base_{suffix}"
    lid_id = f"hinge_lid_{suffix}"
    pin_id = f"hinge_pin_{suffix}"
    height = spec.base_height_mm
    nodes = scenes.stored_nodes(version)
    nodes.extend(
        [
            {
                "id": root_id,
                "name": "Шарнирная крышка",
                "kind": "group",
                "parent_id": None,
                "visible": True,
                "transform": [row[:] for row in scenes.IDENTITY],
                "asset_id": None,
                "instance_of": None,
                "footprint_mm": None,
            },
            _object(base_id, "Основание", assets["base"].id, root_id),
            {
                **_object(lid_id, "Подвижная крышка", assets["lid"].id, root_id),
                "transform": [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, height],
                    [0, 0, 0, 1],
                ],
            },
            {
                **_object(pin_id, "Съёмный штифт", assets["pin"].id, root_id),
                "transform": [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, height],
                    [0, 0, 0, 1],
                ],
            },
        ]
    )
    if ctx.job.created_by is None:
        raise JobFailureError("creator_missing", "mechanism generation needs an owning user")
    details = {
        "schema_version": 1,
        "kind": "hinged_lid",
        "source_version_id": str(version.id),
        "root_node_id": root_id,
        "parts": {"base": base_id, "lid": lid_id, "pin": pin_id},
        "dimensions": spec.model_dump(mode="json"),
        "joint": {
            "type": "revolute",
            "node_id": lid_id,
            "axis": "x",
            "pivot_mm": [0, 0, height],
            "min_angle_deg": 0,
            "max_angle_deg": spec.max_angle_deg,
        },
        "validation": {
            "kind": "kinematic_preview",
            "strength_claim": False,
            "note": "Clearance is geometric; print tolerance and load require physical validation.",
        },
    }
    made = scenes.create_scene_version(
        ctx.db,
        user_id=ctx.job.created_by,
        version_id=version.id,
        nodes=nodes,
        label="Шарнирная крышка",
        operation=HINGED_LID_JOB,
        operation_details=details,
    )
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "mechanism": details,
        "asset_ids": {role: str(asset.id) for role, asset in assets.items()},
    }


@register(SLIDING_LID_JOB)
def handle_sliding_lid(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None or version.project_id != ctx.job.project_id:
        raise JobFailureError("version_not_found", str(version_id))
    try:
        spec = SlidingLidBody.model_validate(ctx.job.input.get("spec"))
        geometry = spec.model_dump(exclude={"max_travel_mm"})
        layout = sliding_lid_layout(**geometry)
        payloads = build_sliding_lid(**geometry)
    except (TypeError, ValueError) as exc:
        raise JobFailureError("invalid_mechanism", str(exc)) from exc
    if spec.max_travel_mm > layout["lid_depth_mm"]:
        raise JobFailureError("invalid_mechanism", "max_travel_mm exceeds the lid length")
    ctx.progress(35, "built mechanism parts")

    assets: dict[str, Any] = {}
    for role, payload in payloads.items():
        asset = store_derived_asset(
            ctx,
            workspace_id=ctx.job.workspace_id,
            data=payload,
            format_id="stl",
            metadata={
                "operation": SLIDING_LID_JOB,
                "mechanism_kind": "sliding_lid",
                "mechanism_role": role,
            },
            created_by=ctx.job.created_by,
        )
        assets[role] = asset
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.progress(65, "stored mechanism parts")

    suffix = uuid.uuid4().hex[:10]
    root_id = f"slide_{suffix}"
    base_id = f"slide_base_{suffix}"
    lid_id = f"slide_lid_{suffix}"
    seat = [0.0, layout["lid_y_mm"], layout["lid_z_mm"]]
    nodes = scenes.stored_nodes(version)
    nodes.extend(
        [
            {
                "id": root_id,
                "name": "Сдвижная крышка",
                "kind": "group",
                "parent_id": None,
                "visible": True,
                "transform": [row[:] for row in scenes.IDENTITY],
                "asset_id": None,
                "instance_of": None,
                "footprint_mm": None,
            },
            _object(base_id, "Корпус с направляющими", assets["base"].id, root_id),
            {
                **_object(lid_id, "Сдвижная крышка", assets["lid"].id, root_id),
                "transform": [
                    [1, 0, 0, seat[0]],
                    [0, 1, 0, seat[1]],
                    [0, 0, 1, seat[2]],
                    [0, 0, 0, 1],
                ],
            },
        ]
    )
    if ctx.job.created_by is None:
        raise JobFailureError("creator_missing", "mechanism generation needs an owning user")
    details = {
        "schema_version": 1,
        "kind": "sliding_lid",
        "source_version_id": str(version.id),
        "root_node_id": root_id,
        "parts": {"base": base_id, "lid": lid_id},
        "dimensions": spec.model_dump(mode="json"),
        "derived_mm": {
            "lid_width_mm": round(layout["lid_width_mm"], 6),
            "lid_depth_mm": round(layout["lid_depth_mm"], 6),
            "overall_height_mm": round(layout["overall_height_mm"], 6),
            "bearing_mm": round(layout["bearing_mm"], 6),
            "retention_mm": round(layout["retention_mm"], 6),
        },
        "joint": {
            "type": "prismatic",
            "node_id": lid_id,
            "axis": "y",
            "origin_mm": seat,
            "min_travel_mm": 0,
            "max_travel_mm": spec.max_travel_mm,
        },
        "validation": {
            "kind": "kinematic_preview",
            "strength_claim": False,
            "note": (
                "Clearance is geometric; print tolerance, friction, fit and load require "
                "physical validation."
            ),
        },
    }
    made = scenes.create_scene_version(
        ctx.db,
        user_id=ctx.job.created_by,
        version_id=version.id,
        nodes=nodes,
        label="Сдвижная крышка",
        operation=SLIDING_LID_JOB,
        operation_details=details,
    )
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(made.id),
        "source_version_id": str(version.id),
        "mechanism": details,
        "asset_ids": {role: str(asset.id) for role, asset in assets.items()},
    }
