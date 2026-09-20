"""Mesh -> editable parametric CAD (T-159..T-161, F-024/F-011).

Recognition is deterministic and runs in the worker sandbox.  This module turns the
recognized prismatic features into the same validated OperationPlan used by AI creation
and manual edits; no generated code is executed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session
from worker.features import FeatureReport, Loop

from app.api.errors import ValidationFailedError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.authz import require_workspace_role

REVERSE_ENGINEER_JOB = "reverse_engineer"


def _profile(loop: Loop) -> tuple[dict[str, Any], list[float]]:
    """Kernel profiles use a lower-left origin for rectangles and a centre for circles."""
    x, y = loop.centre_mm
    if loop.kind == "circle" and loop.diameter_mm:
        return {"kind": "circle", "diameter_mm": loop.diameter_mm}, [x, y]
    if loop.kind == "rectangle" and loop.width_mm and loop.depth_mm:
        return (
            {"kind": "rectangle", "width_mm": loop.width_mm, "depth_mm": loop.depth_mm},
            [x - loop.width_mm / 2, y - loop.depth_mm / 2],
        )
    points = loop.points_mm or []
    if len(points) < 3:
        raise ValidationFailedError("a recognized profile has too few points")
    return {"kind": "polygon", "points_mm": points}, [0.0, 0.0]


def plan_from_report(report: FeatureReport) -> OperationPlan:
    reconstruction = report.reconstruction
    if not report.ok or reconstruction is None or not reconstruction.bands:
        raise ValidationFailedError(
            report.message or "the mesh has no prismatic features to rebuild",
            {"warnings": report.warnings},
        )

    operations: list[dict[str, Any]] = []
    target: str | None = None
    creator_index = 0
    for band in reconstruction.bands:
        height = band.z1_mm - band.z0_mm
        if height <= 0:
            continue
        for outer in band.outer:
            profile, origin = _profile(outer)
            creator_index += 1
            body = f"rebuild_{creator_index}"
            operations.append(
                {
                    "schema_version": 1,
                    "id": body,
                    "type": "extrude",
                    "profile": profile,
                    "height_mm": height,
                    "origin_mm": [origin[0], origin[1], band.z0_mm],
                }
            )
            if target is None:
                target = body
            else:
                operations.append(
                    {
                        "schema_version": 1,
                        "id": f"join_{creator_index}",
                        "type": "boolean",
                        "op": "fuse",
                        "target": target,
                        "tool": body,
                    }
                )
    if target is None:
        raise ValidationFailedError("the recognized mesh produced no solid profiles")

    hole_index = 0
    for cylinder in report.cylinders:
        if cylinder.kind != "hole" or cylinder.from_face == "inside":
            continue
        hole_index += 1
        xyz = cylinder.centre_mm
        axis_index = {"x": 0, "y": 1, "z": 2}[cylinder.axis]
        position = [xyz[index] for index in range(3) if index != axis_index]
        operations.append(
            {
                "schema_version": 1,
                "id": f"hole_{hole_index}",
                "type": "add_hole",
                "target": target,
                "face": {
                    "kind": "face_by_normal",
                    "axis": cylinder.axis,
                    "sign": cylinder.from_face,
                },
                "position_mm": position,
                "diameter_mm": cylinder.diameter_mm,
                "depth_mm": None if cylinder.through else cylinder.length_mm,
            }
        )

    return parse_plan(
        {
            "schema_version": 1,
            "goal": "Editable reconstruction from mesh",
            "assumptions": [
                "The source was aligned to its recognized manufacturing frame",
                "Freeform surface detail remains in the immutable source version",
            ],
            "operations": operations,
            "validation_steps": [
                "compare the rebuilt surface to the source in both directions",
                "report mean, p95 and maximum deviation in millimetres",
            ],
            "expected_outputs": [target],
        }
    )


def enqueue_reconstruction(
    db: Session,
    *,
    user_id: uuid.UUID,
    version_id: uuid.UUID,
    tolerance_mm: float,
    max_levels: int,
    samples: int,
    threads: bool,
    idempotency_key: str | None = None,
) -> Job:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    asset = model_asset_of(db, version)
    if asset is None or asset.format not in REPAIRABLE_FORMATS:
        raise ValidationFailedError(
            "version has no mesh that can be reconstructed",
            {"supported_formats": sorted(REPAIRABLE_FORMATS)},
        )
    return jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=REVERSE_ENGINEER_JOB,
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "tolerance_mm": tolerance_mm,
            "max_levels": max_levels,
            "samples": samples,
            "threads": threads,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
