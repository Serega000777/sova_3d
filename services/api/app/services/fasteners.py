"""Create bounded fastener solids and place them against exact top-face holes."""

from __future__ import annotations

import uuid
from math import cos, radians, sin

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.engineering import fastener as fastener_geometry
from app.engineering import knowledge as kb
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import ProjectVersion
from app.services import fit, modeling, projects
from app.services.authz import require_workspace_role


def create(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    spec: fastener_geometry.FastenerEnvelope,
    label: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Job, uuid.UUID]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if idempotency_key:
        existing = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace_id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None and existing.project_id is not None:
            return existing, existing.project_id
    project = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        name=label or f"Fastener {spec.size}×{spec.length_mm:g}",
        description=(
            "Exact smooth fastener envelope. External thread and drive recess are not modeled."
        ),
    )
    job = modeling.start_with_primitive(
        db,
        user_id=user_id,
        project_id=project.id,
        plan=fastener_geometry.plan_for(spec),
        idempotency_key=idempotency_key,
        provenance={"created_with": "fastener_tool", "fastener": spec.metadata()},
    )
    return job, project.id


def _bbox(version: ProjectVersion, body_name: str | None = None) -> dict[str, list[float]]:
    bodies = (version.provenance or {}).get("bodies")
    if not isinstance(bodies, list):
        raise ValidationFailedError("the exact version has no measured body bounds")
    candidates = [body for body in bodies if isinstance(body, dict)]
    if body_name is not None:
        named = [body for body in candidates if body.get("name") == body_name]
        if named:
            candidates = named
    if len(candidates) != 1:
        raise ValidationFailedError(
            "fastener placement currently needs one exact target body",
            {"body": body_name, "body_count": len(candidates)},
        )
    bbox = candidates[0].get("bbox_mm")
    if not isinstance(bbox, dict):
        raise ValidationFailedError("the exact version has no measured body bounds")
    try:
        minimum = [float(value) for value in bbox["min"]]
        maximum = [float(value) for value in bbox["max"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError("the exact version has invalid measured body bounds") from exc
    if (
        len(minimum) != 3
        or len(maximum) != 3
        or any(maximum[index] <= minimum[index] for index in range(3))
    ):
        raise ValidationFailedError("the exact version has invalid measured body bounds")
    return {"min": minimum, "max": maximum}


def _face_rotation(axis: str, sign: str) -> tuple[float, float, float]:
    """Rotate the fastener's local inward -Z shank onto the selected face's inward normal."""
    rotations = {
        ("x", "+"): (0.0, 90.0, 0.0),
        ("x", "-"): (0.0, -90.0, 0.0),
        ("y", "+"): (-90.0, 0.0, 0.0),
        ("y", "-"): (90.0, 0.0, 0.0),
        ("z", "+"): (0.0, 0.0, 0.0),
        ("z", "-"): (180.0, 0.0, 0.0),
    }
    try:
        return rotations[(axis, sign)]
    except KeyError as exc:
        raise ValidationFailedError("the selected hole has an invalid planar face") from exc


def _rotated(point: list[float], rotation_deg: tuple[float, float, float]) -> list[float]:
    """Extrinsic X then Y then Z rotation, matching worker.fit placement_transform."""
    x, y, z = point
    rx, ry, rz = (radians(value) for value in rotation_deg)
    y, z = y * cos(rx) - z * sin(rx), y * sin(rx) + z * cos(rx)
    x, z = x * cos(ry) + z * sin(ry), -x * sin(ry) + z * cos(ry)
    x, y = x * cos(rz) - y * sin(rz), x * sin(rz) + y * cos(rz)
    return [x, y, z]


def enqueue_fit(
    db: Session,
    *,
    user_id: uuid.UUID,
    target_version_id: uuid.UUID,
    fastener_version_id: uuid.UUID,
    hole_operation_id: str,
    wanted: kb.Fit,
    material_id: str | None,
    language: fit.Language,
    idempotency_key: str | None = None,
) -> Job:
    target = projects.get_version(db, user_id=user_id, version_id=target_version_id)
    fastener_version = projects.get_version(db, user_id=user_id, version_id=fastener_version_id)
    fastener_meta = (fastener_version.provenance or {}).get("fastener")
    if not isinstance(fastener_meta, dict) or fastener_meta.get("schema_version") != 1:
        raise ValidationFailedError("part B is not a verified fastener version")
    operation = next(
        (item for item in fit.operations_of(db, target.id) if item.get("id") == hole_operation_id),
        None,
    )
    if operation is None or operation.get("type") != "add_hole":
        raise ValidationFailedError(
            "the selected operation is not an active exact hole",
            {"hole_operation_id": hole_operation_id},
        )
    face = operation.get("face")
    if not isinstance(face, dict) or face.get("kind") != "face_by_normal":
        raise ValidationFailedError("fastener placement needs an exact planar hole")
    axis = str(face.get("axis") or "")
    sign = str(face.get("sign") or "")
    rotation = _face_rotation(axis, sign)
    position = operation.get("position_mm")
    if not isinstance(position, list | tuple) or len(position) != 2:
        raise ValidationFailedError("the selected hole has no exact in-plane position")
    target_bbox = _bbox(target, str(operation.get("target") or ""))
    fastener_bbox = _bbox(fastener_version, "shank")
    target_centre = [
        (target_bbox["min"][index] + target_bbox["max"][index]) / 2 for index in range(3)
    ]
    fastener_centre = [
        (fastener_bbox["min"][index] + fastener_bbox["max"][index]) / 2 for index in range(3)
    ]
    normal_axis = {"x": 0, "y": 1, "z": 2}[axis]
    seat: list[float] = []
    position_index = 0
    for coordinate in range(3):
        if coordinate == normal_axis:
            seat.append(target_bbox["max" if sign == "+" else "min"][coordinate])
        else:
            seat.append(float(position[position_index]))
            position_index += 1
    # The worker rotates B around its bbox centre, aligns the unrotated centres, then applies
    # this offset. Account for that rotation so the local z=0 head seat lands on the face.
    rotated_fastener_centre = _rotated(fastener_centre, rotation)
    offset = tuple(
        round(seat[index] - target_centre[index] + rotated_fastener_centre[index], 6)
        for index in range(3)
    )
    hole_diameter = float(operation["diameter_mm"])
    target_depth = float(
        operation.get("depth_mm") or (target_bbox["max"][2] - target_bbox["min"][2])
    )
    job = fit.enqueue_fit_test(
        db,
        user_id=user_id,
        version_a_id=target.id,
        version_b_id=fastener_version.id,
        placement=fit.Placement(
            align="centre",
            offset_mm=offset,
            rotate_x_deg=rotation[0],
            rotate_y_deg=rotation[1],
            rotate_z_deg=rotation[2],
        ),
        wanted=wanted,
        material_id=material_id,
        language=language,
        auto_place=False,
        idempotency_key=idempotency_key,
    )
    job.input = {
        **job.input,
        "fastener_fit": {
            "schema_version": 1,
            "hole_operation_id": hole_operation_id,
            "hole_diameter_mm": hole_diameter,
            "hole_depth_mm": target_depth,
            "head_seat_mm": seat,
            "face": {"axis": axis, "sign": sign},
            "fastener": fastener_meta,
        },
    }
    db.flush()
    return job
