"""Load the immutable floor plan attached to a project's current version."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError
from app.engineering.floor_plan import (
    FloorPlan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest
from app.models.core import Project
from app.models.versioning import ProjectVersion
from app.services import projects


@dataclass(frozen=True, slots=True)
class ProjectFloorPlan:
    project: Project
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
