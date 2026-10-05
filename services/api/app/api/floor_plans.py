"""Project floor-plan endpoint: the real plan derived from an immutable house version."""

import uuid

from fastapi import APIRouter

from app.api.deps import DbDep, PrincipalDep
from app.engineering.floor_plan import FloorPlan
from app.services.floor_plans import get_project_floor_plan as load_project_floor_plan

router = APIRouter(tags=["floor-plans"])


@router.get("/projects/{project_id}/floor-plan", response_model=FloorPlan)
def get_project_floor_plan(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> FloorPlan:
    return load_project_floor_plan(
        db, user_id=principal.user_id, project_id=project_id
    ).plan
