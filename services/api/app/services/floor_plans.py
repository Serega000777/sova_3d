"""Load the immutable floor plan attached to a project's current version."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.engineering.floor_plan import (
    BuildingFloorPlans,
    FloorPlan,
    PlanWall,
    RoomRequirement,
    auto_layout_plan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest
from app.engineering.room_shell import RoomShellSpec, build_room_shell_plan
from app.interior_materials import material_by_id
from app.models.core import Project, WorkspaceRole
from app.models.execution import Job, Operation
from app.models.versioning import AssetRole, ProjectVersion, VersionAsset
from app.services import jobs, projects
from app.services.authz import require_workspace_role
from app.services.calibration import EXECUTE_PLAN_JOB


@dataclass(frozen=True, slots=True)
class ProjectFloorPlan:
    project: Project
    version: ProjectVersion
    plan: FloorPlan


@dataclass(frozen=True, slots=True)
class FloorPlanLayout:
    version: ProjectVersion
    plan: FloorPlan
    floor_index: int
    floor_count: int


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    if (
        max(a[0], b[0]) < min(c[0], d[0])
        or max(c[0], d[0]) < min(a[0], b[0])
        or max(a[1], b[1]) < min(c[1], d[1])
        or max(c[1], d[1]) < min(a[1], b[1])
    ):
        return False
    return _cross(a, b, c) * _cross(a, b, d) <= 0 and _cross(c, d, a) * _cross(
        c, d, b
    ) <= 0


def _validate_simple_outline(outline: list[tuple[float, float]]) -> None:
    if len(outline) < 3:
        raise ValidationFailedError("a room needs at least three walls")
    if any(
        math.hypot(
            outline[(index + 1) % len(outline)][0] - point[0],
            outline[(index + 1) % len(outline)][1] - point[1],
        )
        < 100
        for index, point in enumerate(outline)
    ):
        raise ValidationFailedError("moving this wall would make an adjacent wall too short")
    count = len(outline)
    for first in range(count):
        a = outline[first]
        b = outline[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or first == (second + 1) % count:
                continue
            c = outline[second]
            d = outline[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                raise ValidationFailedError(
                    "moving this wall would make the room outline cross itself"
                )


def edit_room_plan_wall(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    base_version_id: uuid.UUID,
    wall_index: int,
    offset_mm: float,
    thickness_mm: float,
    height_mm: float,
    material_id: str | None,
    idempotency_key: str | None = None,
) -> Job:
    """Rebuild one scanned-room wall while retaining the immutable source scan."""
    record = get_project_floor_plan(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, record.project.workspace_id, WorkspaceRole.editor)
    db.execute(sa.select(Project.id).where(Project.id == project_id).with_for_update())
    db.refresh(record.project)
    if record.project.head_version_id != base_version_id or record.version.id != base_version_id:
        raise ConflictError(
            "the room changed; reload before editing its wall",
            {"head_version_id": str(record.project.head_version_id)},
        )
    provenance = record.version.provenance or {}
    room_plan = provenance.get("room_plan")
    shell_payload = room_plan.get("room_shell") if isinstance(room_plan, dict) else None
    if not isinstance(shell_payload, dict):
        raise ValidationFailedError("only a validated RoomPlan room shell can edit scanned walls")
    assert isinstance(room_plan, dict)
    try:
        shell = RoomShellSpec.from_dict(shell_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError("the stored RoomPlan room shell is invalid") from exc
    plan = record.plan
    if len(plan.rooms) != 1 or len(plan.walls) != len(shell.outline_mm):
        raise ValidationFailedError("wall editing requires one simple scanned-room perimeter")
    if wall_index < 0 or wall_index >= len(plan.walls):
        raise ValidationFailedError("the requested wall does not exist")
    if material_id is not None:
        material = material_by_id(material_id)
        if "wall" not in material.tabs:
            raise ValidationFailedError("the selected finish is not available for walls")

    outline = list(shell.outline_mm)
    a = outline[wall_index]
    b = outline[(wall_index + 1) % len(outline)]
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length < 100:
        raise ValidationFailedError("the selected wall is too short to move")
    normal = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
    outline[wall_index] = (a[0] + normal[0] * offset_mm, a[1] + normal[1] * offset_mm)
    outline[(wall_index + 1) % len(outline)] = (
        b[0] + normal[0] * offset_mm,
        b[1] + normal[1] * offset_mm,
    )
    _validate_simple_outline(outline)

    walls = list(plan.walls)
    thicknesses = list(shell.wall_thicknesses_mm or [wall.thickness_mm for wall in walls])
    heights = list(shell.wall_heights_mm or [shell.wall_height_mm for _ in walls])
    materials = list(shell.wall_material_ids or [wall.material_id for wall in walls])
    thicknesses[wall_index] = thickness_mm
    heights[wall_index] = height_mm
    materials[wall_index] = material_id
    walls = [
        PlanWall(
            a=outline[index],
            b=outline[(index + 1) % len(outline)],
            thickness_mm=thicknesses[index],
            height_mm=heights[index],
            material_id=materials[index],
        )
        for index in range(len(outline))
    ]
    for opening in plan.openings:
        wall_length = math.hypot(
            walls[opening.wall].b[0] - walls[opening.wall].a[0],
            walls[opening.wall].b[1] - walls[opening.wall].a[1],
        )
        if opening.offset_mm + opening.width_mm > wall_length + 1:
            raise ValidationFailedError("moving this wall would place an opening outside its wall")
    edited_plan = plan.model_copy(
        update={
            "walls": walls,
            "rooms": [plan.rooms[0].model_copy(update={"outline": outline})],
        }
    )
    edited_shell = RoomShellSpec(
        outline_mm=tuple(outline),
        wall_height_mm=shell.wall_height_mm,
        openings=shell.openings,
        wall_thicknesses_mm=tuple(thicknesses),
        wall_heights_mm=tuple(heights),
        wall_material_ids=tuple(materials),
    )
    operation_plan = build_room_shell_plan(edited_shell)
    links = db.scalars(
        sa.select(VersionAsset).where(VersionAsset.version_id == record.version.id)
    ).all()
    source_scan = next(
        (link.asset_id for link in links if link.role in {AssetRole.scan, AssetRole.model}),
        None,
    )
    if source_scan is None:
        raise ValidationFailedError("the scanned room has no immutable source mesh")
    edit = {
        "schema_version": 1,
        "source_version_id": str(record.version.id),
        "wall_index": wall_index,
        "offset_mm": offset_mm,
        "thickness_mm": thickness_mm,
        "height_mm": height_mm,
        "material_id": material_id,
    }
    next_room_plan = {**room_plan, "room_shell": edited_shell.to_dict()}
    return jobs.enqueue(
        db,
        workspace_id=record.project.workspace_id,
        project_id=record.project.id,
        project_version_id=record.version.id,
        job_type=EXECUTE_PLAN_JOB,
        input={
            "project_id": str(record.project.id),
            "parent_version_id": str(record.version.id),
            "plan": operation_plan.model_dump(mode="json"),
            "label": f"Edit scanned room wall {wall_index + 1}",
            "model_is_room_shell": True,
            "preserved_assets": {AssetRole.scan.value: str(source_scan)},
            "provenance": {
                **provenance,
                "operation": "edit_room_wall",
                "floor_plan": edited_plan.model_dump(mode="json"),
                "room_plan": next_room_plan,
                "room_wall_edit": edit,
            },
        },
        created_by=user_id,
        idempotency_key=idempotency_key,
    )


def get_project_floor_plans(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> BuildingFloorPlans:
    """Return every aligned floor plan, preserving legacy one-plan projects."""
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    if project.head_version_id is None:
        raise NotFoundError("floor_plan", project_id)
    version = projects.get_version(db, user_id=user_id, version_id=project.head_version_id)
    provenance = version.provenance or {}
    raw = provenance.get("floor_plans")
    if isinstance(raw, dict):
        try:
            return BuildingFloorPlans.model_validate(raw)
        except ValidationError:
            pass
    single = get_project_floor_plan(db, user_id=user_id, project_id=project_id)
    floor_height = 3_000.0
    return BuildingFloorPlans.model_validate(
        {
            "version_id": str(version.id),
            "floor_height_mm": floor_height,
            "levels": [
                {
                    "index": 0,
                    "name": "1 этаж",
                    "elevation_mm": 0,
                    "plan": single.plan.model_dump(mode="json"),
                }
            ],
        }
    )


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
    raw_floors = provenance.get("floor_plans")
    if isinstance(raw_floors, dict):
        try:
            building = BuildingFloorPlans.model_validate(raw_floors)
            if building.levels:
                return ProjectFloorPlan(project, version, building.levels[0].plan)
        except ValidationError:
            pass

    # Backward compatibility for house projects created before plans were persisted.
    plan_id = f"project-{project_id}-floor-1"
    try:
        if isinstance(provenance.get("house_box"), dict):
            box_request = HouseBoxRequest(**dict(provenance["house_box"].get("request") or {}))
            plan = floor_plan_from_house_box(box_request, plan_id=plan_id, name=project.name)
            return ProjectFloorPlan(project, version, plan)
        if isinstance(provenance.get("house_walls"), dict):
            walls_request = HouseWallsRequest(
                **dict(provenance["house_walls"].get("request") or {})
            )
            plan = floor_plan_from_house_walls(walls_request, plan_id=plan_id, name=project.name)
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
    room_requirements: list[RoomRequirement] | None = None,
    floor_index: int = 0,
    auto_furnish: bool = False,
) -> FloorPlanLayout:
    """Create a child version with deterministic rooms and doors on one exact floor."""
    record = get_project_floor_plan(db, user_id=user_id, project_id=project_id)
    raw_floor_plans = (record.version.provenance or {}).get("floor_plans")
    building: BuildingFloorPlans | None = None
    if isinstance(raw_floor_plans, dict):
        try:
            building = BuildingFloorPlans.model_validate(raw_floor_plans)
        except ValidationError as exc:
            raise ValidationFailedError("the stored multi-floor plan is invalid") from exc
    floor_count = len(building.levels) if building is not None else 1
    if floor_index < 0 or floor_index >= floor_count:
        raise ValidationFailedError("the requested floor does not exist")
    if auto_furnish and floor_count > 1:
        raise ValidationFailedError(
            "automatic furniture placement is not yet floor-elevation-aware"
        )
    source_plan = building.levels[floor_index].plan if building is not None else record.plan
    if building is None and floor_index != 0:
        raise ValidationFailedError("the requested floor does not exist")
    if building is not None:
        selected_level = building.levels[floor_index]
        if selected_level.index != floor_index:
            raise ValidationFailedError(
                "the stored multi-floor plan has inconsistent floor indices"
            )
    require_workspace_role(db, user_id, record.project.workspace_id, WorkspaceRole.editor)
    db.execute(sa.select(Project.id).where(Project.id == project_id).with_for_update())
    db.refresh(record.project)
    if record.project.head_version_id != base_version_id or record.version.id != base_version_id:
        raise ConflictError(
            "the floor plan changed; reload before generating rooms",
            {"head_version_id": str(record.project.head_version_id)},
        )
    try:
        layout = auto_layout_plan(
            source_plan,
            room_count=room_count,
            partition_thickness_mm=partition_thickness_mm,
            door_width_mm=door_width_mm,
            room_requirements=room_requirements,
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc

    plan = layout.plan
    layout_provenance: dict[str, object] = {
        "kind": layout.kind,
        "room_count": room_count,
        "partition_thickness_mm": partition_thickness_mm,
        "door_width_mm": door_width_mm,
        "source_version_id": str(record.version.id),
        "floor_index": floor_index,
        "plan_id": plan.id,
        "room_requirements": (
            [item.model_dump(mode="json") for item in room_requirements]
            if room_requirements is not None
            else None
        ),
    }
    if layout.zone_room_counts is not None and layout.seam is not None:
        layout_provenance.update(
            {
                "zone_room_counts": list(layout.zone_room_counts),
                "seam": {
                    "a": list(layout.seam[0]),
                    "b": list(layout.seam[1]),
                },
            }
        )

    links = db.scalars(
        sa.select(VersionAsset).where(VersionAsset.version_id == record.version.id)
    ).all()
    provenance = {
        **(record.version.provenance or {}),
        "floor_plan_layout": layout_provenance,
    }
    if building is None:
        provenance["floor_plan"] = plan.model_dump(mode="json")
    else:
        levels = [
            level.model_copy(update={"plan": plan}) if level.index == floor_index else level
            for level in building.levels
        ]
        updated_building = building.model_copy(update={"levels": levels})
        provenance["floor_plan"] = levels[0].plan.model_dump(mode="json")
        provenance["floor_plans"] = updated_building.model_dump(mode="json")

    version = projects.create_version_internal(
        db,
        project_id=project_id,
        parent_version_id=record.version.id,
        label=f"Automatic {room_count}-room floor plan",
        provenance=provenance,
        assets={AssetRole(link.role): link.asset_id for link in links},
        finalize=False,
        created_by=user_id,
    )
    if building is not None:
        version.provenance = {
            **(version.provenance or {}),
            "floor_plans": updated_building.model_copy(
                update={"version_id": str(version.id)}
            ).model_dump(mode="json"),
        }
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
                enabled=operation.enabled,
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
                "floor_index": floor_index,
                "kind": layout.kind,
                "room_count": room_count,
                "partition_thickness_mm": partition_thickness_mm,
                "door_width_mm": door_width_mm,
                "room_requirements": (
                    [item.model_dump(mode="json") for item in room_requirements]
                    if room_requirements is not None
                    else None
                ),
            },
            entity_refs=[],
        )
    )
    db.flush()
    projects.finalize_version(db, version)
    return FloorPlanLayout(
        version=version,
        plan=plan,
        floor_index=floor_index,
        floor_count=floor_count,
    )
