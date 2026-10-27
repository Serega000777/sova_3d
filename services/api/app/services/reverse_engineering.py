"""Mesh -> editable parametric CAD (T-159..T-161, F-024/F-011).

Recognition is deterministic and runs in the worker sandbox.  This module turns the
recognized prismatic features into the same validated OperationPlan used by AI creation
and manual edits; no generated code is executed.
"""

from __future__ import annotations

import uuid
from math import cos, dist, pi, sin
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from worker.features import FeatureReport, Loop

from app.api.errors import ValidationFailedError
from app.geometry.operations import OperationPlan, parse_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.services import jobs, projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.authz import require_workspace_role

REVERSE_ENGINEER_JOB = "reverse_engineer"
MissingHalf = Literal["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"]


def durable_restoration_evidence(
    restore_missing_half: MissingHalf | None,
    reinforce_thickness_percent: float | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    restoration = (
        {
            "mode": "mirrored_missing_half",
            "boundary": restore_missing_half,
            "requires_physical_validation": True,
        }
        if restore_missing_half is not None
        else None
    )
    reinforcement = (
        {
            "mode": "thickness_percent",
            "percent": reinforce_thickness_percent,
            "datum": "minimum_z",
            "certified": False,
            "requires_physical_validation": True,
        }
        if reinforce_thickness_percent is not None
        else None
    )
    return restoration, reinforcement


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


def _vertical_edge_treatment(report: FeatureReport) -> tuple[str, float] | None:
    """Return an exact treatment only when one measured prism makes it unambiguous.

    The recognizer stores rounded/chamfered rectangle corners on the outline itself.
    Replaying that measurement over several bands or outer islands would need stable
    per-body edge identities, so those cases deliberately remain report-only.
    """
    reconstruction = report.reconstruction
    if reconstruction is None or len(reconstruction.bands) != 1:
        return None
    band = reconstruction.bands[0]
    if len(band.outer) != 1:
        return None
    outline = band.outer[0]
    if outline.kind != "rectangle":
        return None
    if outline.corner_radius_mm and outline.chamfer_mm:
        raise ValidationFailedError("a recognized rectangle cannot be both rounded and chamfered")
    if outline.corner_radius_mm:
        return ("fillet", outline.corner_radius_mm)
    if outline.chamfer_mm:
        return ("chamfer", outline.chamfer_mm)
    return None


def _end_edge_treatments(report: FeatureReport) -> list[tuple[str, str, float]]:
    """Return measured top/bottom treatments only for one unambiguous outer wire.

    ``edges_of_face`` intentionally includes inner wires. Applying it to a face with a
    hole would round/chamfer the hole rim as well, which the feature report does not
    prove. Keep those cases report-only until the kernel has an outer-wire selector.
    """
    reconstruction = report.reconstruction
    if reconstruction is None or len(reconstruction.bands) != 1:
        return []
    band = reconstruction.bands[0]
    if len(band.outer) != 1 or band.holes or reconstruction.side_holes:
        return []
    if any(cylinder.kind == "hole" for cylinder in report.cylinders):
        return []
    treatments: list[tuple[str, str, float]] = []
    for edge in (reconstruction.bottom_edge, reconstruction.top_edge):
        if edge is not None:
            treatments.append((edge.where, edge.kind, edge.size_mm))
    return treatments


def _standard_internal_thread(report: FeatureReport, cylinder: Any) -> Any | None:
    """Match one high-confidence standard thread to its source hole, or refuse ambiguity."""
    candidates = [
        thread
        for thread in report.threads
        if thread.on == "hole"
        and thread.axis == cylinder.axis
        and thread.designation is not None
        and thread.confidence >= 0.9
        and dist(thread.centre_mm, cylinder.centre_mm) <= max(0.2, 0.05 * thread.minor_diameter_mm)
        and min(
            abs(cylinder.diameter_mm - thread.minor_diameter_mm),
            abs(cylinder.diameter_mm - thread.major_diameter_mm),
        )
        <= max(0.5, 0.15 * thread.major_diameter_mm)
    ]
    if len(candidates) != 1:
        return None
    thread = candidates[0]
    radial_depth = (thread.major_diameter_mm - thread.minor_diameter_mm) / 2
    turns = cylinder.length_mm / thread.pitch_mm
    if radial_depth <= 0 or thread.pitch_mm < radial_depth or turns < 2.5 or turns > 128:
        return None
    return thread


def _pattern_points(pattern: Any) -> tuple[list[tuple[float, float]], dict[str, Any]] | None:
    """Expand one recognized Z-hole pattern and preserve its editable parameters."""
    cx, cy = pattern.centre_mm
    if pattern.kind == "linear" and pattern.pitch_mm and pattern.angle_deg is not None:
        angle = pattern.angle_deg * pi / 180
        points = [
            (
                cx + (index - (pattern.count - 1) / 2) * pattern.pitch_mm * cos(angle),
                cy + (index - (pattern.count - 1) / 2) * pattern.pitch_mm * sin(angle),
            )
            for index in range(pattern.count)
        ]
        return points, {
            "kind": "linear",
            "count": pattern.count,
            "pitch_mm": pattern.pitch_mm,
            "angle_deg": pattern.angle_deg,
        }
    if (
        pattern.kind == "grid"
        and pattern.columns
        and pattern.rows
        and pattern.pitch_x_mm
        and pattern.pitch_y_mm
        and pattern.columns * pattern.rows == pattern.count
    ):
        points = [
            (
                cx + (column - (pattern.columns - 1) / 2) * pattern.pitch_x_mm,
                cy + (row - (pattern.rows - 1) / 2) * pattern.pitch_y_mm,
            )
            for row in range(pattern.rows)
            for column in range(pattern.columns)
        ]
        return points, {
            "kind": "grid",
            "columns": pattern.columns,
            "rows": pattern.rows,
            "pitch_x_mm": pattern.pitch_x_mm,
            "pitch_y_mm": pattern.pitch_y_mm,
        }
    if pattern.kind == "circular" and pattern.radius_mm and pattern.start_angle_deg is not None:
        angles = [
            (pattern.start_angle_deg + 360 * index / pattern.count) * pi / 180
            for index in range(pattern.count)
        ]
        points = [
            (
                cx + pattern.radius_mm * cos(angle),
                cy + pattern.radius_mm * sin(angle),
            )
            for angle in angles
        ]
        return points, {
            "kind": "circular",
            "count": pattern.count,
            "radius_mm": pattern.radius_mm,
            "start_angle_deg": pattern.start_angle_deg,
        }
    return None


def _recognized_hole_patterns(
    report: FeatureReport, target: str
) -> tuple[list[dict[str, Any]], set[int]]:
    """Promote only complete, one-to-one Z-hole groups; leave every ambiguity expanded."""
    operations: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for pattern in report.patterns:
        expanded = _pattern_points(pattern)
        if expanded is None:
            continue
        expected, specification = expanded
        tolerance = max(0.2, 0.05 * pattern.diameter_mm)
        matched: list[int] = []
        for point in expected:
            candidates = [
                index
                for index, cylinder in enumerate(report.cylinders)
                if index not in consumed
                and index not in matched
                and cylinder.kind == "hole"
                and cylinder.axis == "z"
                and cylinder.from_face != "inside"
                and abs(cylinder.diameter_mm - pattern.diameter_mm) <= tolerance
                and dist(cylinder.centre_mm[:2], point) <= tolerance
                and _standard_internal_thread(report, cylinder) is None
            ]
            if len(candidates) != 1:
                matched = []
                break
            matched.append(candidates[0])
        if len(matched) != pattern.count:
            continue
        members = [report.cylinders[index] for index in matched]
        first = members[0]
        if any(
            member.from_face != first.from_face
            or member.through != first.through
            or abs(member.length_mm - first.length_mm) > tolerance
            for member in members[1:]
        ):
            continue
        operations.append(
            {
                "schema_version": 1,
                "id": f"hole_pattern_{len(operations) + 1}",
                "type": "add_hole_pattern",
                "target": target,
                "face": {"kind": "face_by_normal", "axis": "z", "sign": first.from_face},
                "centre_mm": list(pattern.centre_mm),
                "diameter_mm": pattern.diameter_mm,
                "depth_mm": None if first.through else first.length_mm,
                "pattern": specification,
            }
        )
        consumed.update(matched)
    return operations, consumed


def plan_from_report(
    report: FeatureReport,
    *,
    restore_missing_half: MissingHalf | None = None,
    reinforce_thickness_percent: float | None = None,
) -> OperationPlan:
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

    pattern_operations, patterned_cylinders = _recognized_hole_patterns(report, target)
    operations.extend(pattern_operations)

    hole_index = 0
    for cylinder_index, cylinder in enumerate(report.cylinders):
        if cylinder.kind != "hole" or cylinder.from_face == "inside":
            continue
        if cylinder_index in patterned_cylinders:
            continue
        hole_index += 1
        xyz = cylinder.centre_mm
        axis_index = {"x": 0, "y": 1, "z": 2}[cylinder.axis]
        position = [xyz[index] for index in range(3) if index != axis_index]
        thread = _standard_internal_thread(report, cylinder)
        if thread is not None:
            operations.append(
                {
                    "schema_version": 1,
                    "id": f"thread_{hole_index}",
                    "type": "add_internal_thread",
                    "target": target,
                    "face": {
                        "kind": "face_by_normal",
                        "axis": cylinder.axis,
                        "sign": cylinder.from_face,
                    },
                    "position_mm": position,
                    "major_diameter_mm": thread.major_diameter_mm,
                    "minor_diameter_mm": thread.minor_diameter_mm,
                    "pitch_mm": thread.pitch_mm,
                    "depth_mm": None if cylinder.through else cylinder.length_mm,
                    "handedness": "right",
                }
            )
            continue
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

    edge_treatment = _vertical_edge_treatment(report)
    if edge_treatment is not None:
        kind, size_mm = edge_treatment
        operations.append(
            {
                "schema_version": 1,
                "id": "recognized_vertical_edges",
                "type": kind,
                "target": target,
                "edges": {
                    "kind": "edges_parallel_to",
                    "axis": "z",
                    "outer": True,
                },
                ("radius_mm" if kind == "fillet" else "distance_mm"): size_mm,
            }
        )

    for where, kind, size_mm in _end_edge_treatments(report):
        operations.append(
            {
                "schema_version": 1,
                "id": f"recognized_{where}_edges",
                "type": kind,
                "target": target,
                "edges": {
                    "kind": "edges_of_face",
                    "face": {
                        "kind": "face_by_normal",
                        "axis": "z",
                        "sign": "+" if where == "top" else "-",
                    },
                },
                ("radius_mm" if kind == "fillet" else "distance_mm"): size_mm,
            }
        )

    if restore_missing_half is not None:
        axis_name, boundary = restore_missing_half.split("_", maxsplit=1)
        axis = {"x": 0, "y": 1, "z": 2}[axis_name]
        extent = reconstruction.extents_mm[axis]
        if extent <= 0:
            raise ValidationFailedError("the reconstruction has no extent on the mirror axis")
        offset = 0.0 if boundary == "min" else extent
        operations.append(
            {
                "schema_version": 1,
                "id": "restore_missing_half",
                "type": "mirror",
                "target": target,
                "axis": axis_name,
                "offset_mm": offset,
                "keep_original": True,
            }
        )

    reinforced_height: float | None = None
    if reinforce_thickness_percent is not None:
        if not 0 < reinforce_thickness_percent <= 50:
            raise ValidationFailedError("reinforcement must be between 0 and 50 percent")
        if reconstruction.fidelity == "freeform" or len(reconstruction.bands) != 1:
            raise ValidationFailedError(
                "thickness reinforcement requires one prismatic reconstruction band"
            )
        if reconstruction.side_holes:
            raise ValidationFailedError(
                "thickness reinforcement would distort a side hole; edit it manually"
            )
        if restore_missing_half in {"z_min", "z_max"}:
            raise ValidationFailedError("thickness reinforcement cannot share the restoration axis")
        reinforced_height = round(
            reconstruction.extents_mm[2] * (1 + reinforce_thickness_percent / 100), 6
        )
        operations.append(
            {
                "schema_version": 1,
                "id": "reinforce_thickness",
                "type": "set_dimensions",
                "target": target,
                "height_mm": reinforced_height,
            }
        )

    return parse_plan(
        {
            "schema_version": 1,
            "goal": "Editable reconstruction from mesh",
            "assumptions": [
                "The source was aligned to its recognized manufacturing frame",
                "Freeform surface detail remains in the immutable source version",
                *(
                    [
                        f"The missing fragment is the mirror of the observed part across "
                        f"the {restore_missing_half} boundary plane"
                    ]
                    if restore_missing_half is not None
                    else []
                ),
                *(
                    [
                        f"The replacement thickness is increased by "
                        f"{reinforce_thickness_percent:g}% from the minimum-Z datum; this is "
                        "geometric reinforcement, not a certified load calculation"
                    ]
                    if reinforced_height is not None and reinforce_thickness_percent is not None
                    else []
                ),
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
    restore_missing_half: MissingHalf | None = None,
    reinforce_thickness_percent: float | None = None,
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
            "restore_missing_half": restore_missing_half,
            "reinforce_thickness_percent": reinforce_thickness_percent,
        },
        created_by=user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
