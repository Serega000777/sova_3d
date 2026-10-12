from app.engineering.floor_plan import FloorPlan, PlanRoom, PlanWall
from app.engineering.furniture_placement import FurnitureFootprint, placement_conflict


def _plan():
    corners = [(0.0, 0.0), (4_000.0, 0.0), (4_000.0, 5_000.0), (0.0, 5_000.0)]
    return FloorPlan(
        id="room",
        name="Room",
        walls=[
            PlanWall(a=point, b=corners[(index + 1) % 4], thickness_mm=120)
            for index, point in enumerate(corners)
        ],
        rooms=[PlanRoom(name="Room", outline=corners)],
    )


def test_clearance_accepts_a_rotated_item_inside_the_room() -> None:
    conflict = placement_conflict(
        _plan(),
        FurnitureFootprint("new:bed", (2_000, 2_500), 1_600, 2_100, 90),
        clearance_mm=200,
        furniture=[],
    )
    assert conflict is None


def test_clearance_rejects_wall_and_outside_room() -> None:
    wall = placement_conflict(
        _plan(),
        FurnitureFootprint("new:chair", (380, 2_500), 480, 520, 0),
        clearance_mm=100,
        furniture=[],
    )
    outside = placement_conflict(
        _plan(),
        FurnitureFootprint("new:chair", (-500, 2_500), 480, 520, 0),
        clearance_mm=0,
        furniture=[],
    )
    assert wall == ("wall_clearance", "wall:3")
    assert outside == ("outside_room", "new:chair")


def test_clearance_rejects_an_existing_rotated_furniture_footprint() -> None:
    conflict = placement_conflict(
        _plan(),
        FurnitureFootprint("new:chair", (2_000, 2_500), 480, 520, 0),
        clearance_mm=300,
        furniture=[FurnitureFootprint("sofa_1", (2_800, 2_500), 900, 2_100, 90)],
    )
    assert conflict == ("furniture_clearance", "sofa_1")
