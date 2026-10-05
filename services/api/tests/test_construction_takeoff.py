import uuid

from app.engineering.construction_takeoff import ConstructionTakeoff, build_construction_takeoff
from app.engineering.floor_plan import FloorPlan, PlanOpening, PlanRoom, PlanWall


def _quantities(report: ConstructionTakeoff) -> dict[str, float]:
    return {line.code: line.quantity for line in report.quantities}


def test_takeoff_measures_floor_walls_and_opening_counts() -> None:
    plan = FloorPlan(
        id="plan-1",
        name="Measured house",
        walls=[
            PlanWall(a=(0, 0), b=(10_000, 0), thickness_mm=250),
            PlanWall(a=(10_000, 0), b=(10_000, 8_000), thickness_mm=250),
            PlanWall(a=(10_000, 8_000), b=(0, 8_000), thickness_mm=250),
            PlanWall(a=(0, 8_000), b=(0, 0), thickness_mm=250),
        ],
        openings=[
            PlanOpening(wall=0, offset_mm=2_000, width_mm=1_000, kind="door"),
            PlanOpening(wall=2, offset_mm=1_000, width_mm=1_500, kind="window"),
        ],
        rooms=[
            PlanRoom(
                name="Ground floor",
                outline=[(0, 0), (10_000, 0), (10_000, 8_000), (0, 8_000)],
            )
        ],
    )

    report = build_construction_takeoff(
        plan,
        project_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        floors=2,
        floor_height_mm=3_000,
    )

    assert _quantities(report) == {
        "footprint_area": 80.0,
        "total_floor_area": 160.0,
        "plan_wall_length": 36.0,
        "door_count": 1.0,
        "window_count": 1.0,
        "gross_wall_area": 216.0,
        "gross_wall_volume": 54.0,
    }
    assert report.priced is False and report.currency is None
    assert report.floors == 2 and report.floor_height_mm == 3_000


def test_takeoff_omits_vertical_quantities_when_height_is_unknown() -> None:
    plan = FloorPlan(
        id="room-plan",
        name="Room",
        walls=[PlanWall(a=(0, 0), b=(4_000, 0), thickness_mm=120)],
        rooms=[PlanRoom(name="Room", outline=[(0, 0), (4_000, 0), (4_000, 5_000)])],
    )

    report = build_construction_takeoff(
        plan, project_id=uuid.uuid4(), version_id=uuid.uuid4()
    )

    assert set(_quantities(report)) == {
        "footprint_area",
        "total_floor_area",
        "plan_wall_length",
        "door_count",
        "window_count",
    }
    assert any("height is unavailable" in warning for warning in report.warnings)
