"""Project floor-plan endpoint: the real plan derived from an immutable house version."""

import uuid

from fastapi import APIRouter
from pydantic import ValidationError

from app.api.deps import DbDep, PrincipalDep
from app.api.errors import NotFoundError
from app.engineering.floor_plan import (
    FloorPlan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest
from app.services import projects

router = APIRouter(tags=["floor-plans"])


@router.get("/projects/{project_id}/floor-plan", response_model=FloorPlan)
def get_project_floor_plan(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> FloorPlan:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    if project.head_version_id is None:
        raise NotFoundError("floor_plan", project_id)
    version = projects.get_version(
        db, user_id=principal.user_id, version_id=project.head_version_id
    )
    provenance = version.provenance or {}
    raw = provenance.get("floor_plan")
    if isinstance(raw, dict):
        try:
            return FloorPlan.model_validate(raw)
        except ValidationError:
            pass

    # Backward compatibility for house projects created before plans were persisted.
    plan_id = f"project-{project_id}-floor-1"
    try:
        if isinstance(provenance.get("house_box"), dict):
            box_request = HouseBoxRequest(
                **dict(provenance["house_box"].get("request") or {})
            )
            return floor_plan_from_house_box(
                box_request, plan_id=plan_id, name=project.name
            )
        if isinstance(provenance.get("house_walls"), dict):
            walls_request = HouseWallsRequest(
                **dict(provenance["house_walls"].get("request") or {})
            )
            return floor_plan_from_house_walls(
                walls_request, plan_id=plan_id, name=project.name
            )
    except (TypeError, ValueError, ValidationError):
        pass
    raise NotFoundError("floor_plan", project_id)
