"""Load the immutable floor plan attached to a project's current version."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.engineering.floor_plan import (
    FloorPlan,
    auto_layout_rectangular_plan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest
from app.models.core import Project, WorkspaceRole
from app.models.execution import Operation
from app.models.versioning import AssetRole, ProjectVersion, VersionAsset
from app.services import projects
from app.services.authz import require_workspace_role


@dataclass(frozen=True, slots=True)
class ProjectFloorPlan:
    project: Project
    version: ProjectVersion
    plan: FloorPlan


@dataclass(frozen=True, slots=True)
class FloorPlanLayout:
    version: ProjectVersion
    plan: FloorPlan


def get_project_floor_plan(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectFloorPlan:
    """Return a project's current plan, failing closed for missing or malformed data."""
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    if project.head_version_id is None:
        raise NotFoundError("floor_plan", project_id)
    version = projects.get_version(db, user_id=user_id, version_id=project.head_version_id)
    provenance = version.provenance or {}
    raw = provenance.get("floor_plan")
    if isinstance(raw, dict):
        try:
            return ProjectFloorPlan(project, version, FloorPlan.model_validate(raw))
        except ValidationError:
            pass

    # Backward compatibility for house projects created before plans were persisted.
    plan_id = f"project-{project_id}-floor-1"
    try:
        if isinstance(provenance.get("house_box"), dict):
            box_request = HouseBoxRequest(
                **dict(provenance["house_box"].get("request") or {})
            )
            plan = floor_plan_from_house_box(
                box_request, plan_id=plan_id, name=project.name
            )
            return ProjectFloorPlan(project, version, plan)
        if isinstance(provenance.get("house_walls"), dict):
            walls_request = HouseWallsRequest(
                **dict(provenance["house_walls"].get("request") or {})
            )
            plan = floor_plan_from_house_walls(
                walls_request, plan_id=plan_id, name=project.name
            )
            return ProjectFloorPlan(project, version, plan)
    except (TypeError, ValueError, ValidationError):
        pass
    raise NotFoundError("floor_plan", project_id)


def auto_layout_project_floor_plan(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    base_version_id: uuid.UUID,
    room_count: int,
    partition_thickness_mm: float,
    door_width_mm: float,
) -> FloorPlanLayout:
    """Create a child version whose plan has deterministic rectangular rooms and doors."""
    record = get_project_floor_plan(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, record.project.workspace_id, WorkspaceRole.editor)
    db.execute(sa.select(Project.id).where(Project.id == project_id).with_for_update())
    db.refresh(record.project)
    if record.project.head_version_id != base_version_id or record.version.id != base_version_id:
        raise ConflictError(
            "the floor plan changed; reload before generating rooms",
            {"head_version_id": str(record.project.head_version_id)},
        )
    try:
        plan = auto_layout_rectangular_plan(
            record.plan,
            room_count=room_count,
            partition_thickness_mm=partition_thickness_mm,
            door_width_mm=door_width_mm,
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc

    links = db.scalars(
        sa.select(VersionAsset).where(VersionAsset.version_id == record.version.id)
    ).all()
    version = projects.create_version_internal(
        db,
        project_id=project_id,
        parent_version_id=record.version.id,
        label=f"Automatic {room_count}-room floor plan",
        provenance={
            **(record.version.provenance or {}),
            "floor_plan": plan.model_dump(mode="json"),
            "floor_plan_layout": {
                "kind": "equal_strips_v1",
                "room_count": room_count,
                "partition_thickness_mm": partition_thickness_mm,
                "door_width_mm": door_width_mm,
                "source_version_id": str(record.version.id),
            },
        },
        assets={AssetRole(link.role): link.asset_id for link in links},
        finalize=False,
        created_by=user_id,
    )
    existing = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == record.version.id)
        .order_by(Operation.sequence_no)
    ).all()
    for operation in existing:
        db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=operation.sequence_no,
                operation_type=operation.operation_type,
                schema_version=operation.schema_version,
                params=operation.params,
                entity_refs=operation.entity_refs,
            )
        )
    db.add(
        Operation(
            project_version_id=version.id,
            sequence_no=max((operation.sequence_no for operation in existing), default=0) + 1,
            operation_type="update_floor_plan",
            schema_version=1,
            params={
                "plan_id": plan.id,
                "kind": "equal_strips_v1",
                "room_count": room_count,
                "partition_thickness_mm": partition_thickness_mm,
                "door_width_mm": door_width_mm,
            },
            entity_refs=[],
        )
    )
    db.flush()
    projects.finalize_version(db, version)
    return FloorPlanLayout(version=version, plan=plan)
