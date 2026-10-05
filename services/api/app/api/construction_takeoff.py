"""Read-only construction quantity takeoff for the current project version."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DbDep, PrincipalDep
from app.engineering.construction_takeoff import ConstructionTakeoff, build_construction_takeoff
from app.services.floor_plans import get_project_floor_plan

router = APIRouter(tags=["house-design"])


def _house_dimensions(provenance: dict[str, Any]) -> tuple[int, float | None]:
    for key in ("house_box", "house_walls"):
        raw = provenance.get(key)
        if not isinstance(raw, dict):
            continue
        request = raw.get("request")
        if not isinstance(request, dict):
            continue
        floors = request.get("floors")
        height = request.get("floor_height_mm")
        if (
            isinstance(floors, int)
            and not isinstance(floors, bool)
            and floors >= 1
            and isinstance(height, (int, float))
            and not isinstance(height, bool)
            and height > 0
        ):
            return floors, float(height)
    return 1, None


@router.get(
    "/projects/{project_id}/construction-takeoff", response_model=ConstructionTakeoff
)
def get_construction_takeoff(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> ConstructionTakeoff:
    record = get_project_floor_plan(
        db, user_id=principal.user_id, project_id=project_id
    )
    floors, floor_height_mm = _house_dimensions(record.version.provenance or {})
    return build_construction_takeoff(
        record.plan,
        project_id=project_id,
        version_id=record.version.id,
        floors=floors,
        floor_height_mm=floor_height_mm,
    )
