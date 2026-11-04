import pytest

from app.engineering.room_plan import (
    RoomPlanCapture,
    RoomPlanStructureCapture,
    floor_plan_from_room_plan,
    floor_plan_from_room_plan_structure,
)

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def capture(**updates: object) -> RoomPlanCapture:
    payload: dict[str, object] = {
        "room_id": "apple-room-1",
        # Deliberately shuffled, reversed and separated by small measurement gaps.
        "walls": [
            {"identifier": "north", "a_m": (4.02, 3.01), "b_m": (-0.01, 3.0), "height_m": 2.71},
            {"identifier": "west", "a_m": (0.0, 3.02), "b_m": (0.01, -0.02), "height_m": 2.7},
            {"identifier": "south", "a_m": (0.0, 0.0), "b_m": (4.0, 0.01), "height_m": 2.69},
            {"identifier": "east", "a_m": (4.01, -0.01), "b_m": (4.0, 3.0), "height_m": 2.7},
        ],
        "openings": [
            {
                "identifier": "door-1",
                "parent_wall_id": "south",
                "center_m": (2.0, 0.01),
                "width_m": 0.9,
                "dimensions_m": (0.9, 2.1, 0.12),
                "kind": "door",
            },
            {
                "identifier": "window-1",
                "parent_wall_id": None,
                "center_m": (4.0, 1.5),
                "width_m": 1.2,
                "dimensions_m": (1.2, 1.2, 0.12),
                "kind": "window",
            },
            {
                "identifier": "passage-1",
                "parent_wall_id": "west",
                "center_m": (0, 1.5),
                "width_m": 1.0,
                "dimensions_m": (1.0, 2.2, 0.12),
                "kind": "opening",
            },
        ],
    }
    payload.update(updates)
    return RoomPlanCapture.model_validate(payload)


def structure_room(
    room_id: str, x0: float, x1: float, floor_elevation_m: float = 0
) -> RoomPlanCapture:
    transform = [*IDENTITY]
    transform[13] = floor_elevation_m + 1.35
    walls = [
        ("south", (x0, 0), (x1, 0), x1 - x0),
        ("east", (x1, 0), (x1, 3), 3),
        ("north", (x1, 3), (x0, 3), x1 - x0),
        ("west", (x0, 3), (x0, 0), 3),
    ]
    return RoomPlanCapture.model_validate(
        {
            "schema_version": 2,
            "room_id": room_id,
            "floor_elevation_m": floor_elevation_m,
            "walls": [
                {
                    "identifier": f"{room_id}-{identifier}",
                    "a_m": a,
                    "b_m": b,
                    "height_m": 2.7,
                    "transform_m": transform,
                    "dimensions_m": [width, 2.7, 0.12],
                }
                for identifier, a, b, width in walls
            ],
            "openings": [],
        }
    )


def test_roomplan_surfaces_become_a_closed_metric_floor_plan() -> None:
    converted = floor_plan_from_room_plan(capture(), plan_id="scan-plan", name="Kitchen")

    assert converted.plan.id == "scan-plan"
    assert converted.plan.name == "Kitchen"
    assert len(converted.plan.walls) == 4
    assert converted.plan.walls[-1].b == converted.plan.walls[0].a
    assert converted.plan.rooms[0].outline == [wall.a for wall in converted.plan.walls]
    assert converted.floor_height_mm == pytest.approx(2_700)
    assert [(opening.kind, opening.width_mm) for opening in converted.plan.openings] == [
        ("door", 900),
        ("window", 1_200),
        ("opening", 1_000),
    ]
    assert converted.plan.openings[0].offset_mm == pytest.approx(1_550, abs=25)
    assert [opening.height_mm for opening in converted.plan.openings] == [
        pytest.approx(2_100),
        pytest.approx(1_200),
        pytest.approx(2_200),
    ]
    assert converted.warnings == ()


def test_opening_taller_than_wall_is_kept_and_reported() -> None:
    raw = capture(
        openings=[
            {
                "identifier": "tall-door",
                "parent_wall_id": "south",
                "center_m": (2.0, 0.01),
                "width_m": 0.9,
                "dimensions_m": (0.9, 3.1, 0.12),
                "kind": "door",
            }
        ]
    )

    converted = floor_plan_from_room_plan(raw, plan_id="room", name="Room")

    assert converted.plan.openings[0].height_mm == pytest.approx(3_100)
    assert converted.warnings == ("opening tall-door is taller than its wall",)


def test_roomplan_refuses_disconnected_or_unclosed_walls() -> None:
    broken = capture(
        walls=[
            {"identifier": "a", "a_m": (0, 0), "b_m": (4, 0), "height_m": 2.7},
            {"identifier": "b", "a_m": (4, 0), "b_m": (4, 3), "height_m": 2.7},
            {"identifier": "c", "a_m": (20, 20), "b_m": (24, 20), "height_m": 2.7},
        ],
        openings=[],
    )

    with pytest.raises(ValueError, match="connected room perimeter|close"):
        floor_plan_from_room_plan(broken, plan_id="broken", name="Broken")


def test_unmatched_opening_is_reported_instead_of_fabricated() -> None:
    raw = capture(
        openings=[
            {
                "identifier": "floating-door",
                "parent_wall_id": None,
                "center_m": (20, 20),
                "width_m": 0.9,
                "kind": "door",
            }
        ]
    )
    converted = floor_plan_from_room_plan(raw, plan_id="room", name="Room")

    assert converted.plan.openings == []
    assert converted.warnings == ("opening floating-door could not be matched to a wall",)


def test_self_intersecting_roomplan_outline_is_rejected() -> None:
    crossed = capture(
        walls=[
            {"identifier": "a", "a_m": (0, 0), "b_m": (4, 3), "height_m": 2.7},
            {"identifier": "b", "a_m": (4, 3), "b_m": (0, 3), "height_m": 2.7},
            {"identifier": "c", "a_m": (0, 3), "b_m": (4, 0), "height_m": 2.7},
            {"identifier": "d", "a_m": (4, 0), "b_m": (0, 0), "height_m": 2.7},
        ],
        openings=[],
    )

    with pytest.raises(ValueError, match="self-intersecting"):
        floor_plan_from_room_plan(crossed, plan_id="crossed", name="Crossed")


def test_roomplan_structure_preserves_shared_world_offsets() -> None:
    structure = RoomPlanStructureCapture.model_validate(
        {
            "structure_id": "home-1",
            "coordinate_space": "shared_arkit_world",
            "rooms": [structure_room("kitchen", 0, 4), structure_room("hall", 4, 7)],
        }
    )

    converted = floor_plan_from_room_plan_structure(structure, plan_id="home-plan", name="Home")

    assert converted.room_ids == ("kitchen", "hall")
    assert len(converted.plan.rooms) == 2
    assert len(converted.plan.walls) == 8
    assert min(point[0] for point in converted.plan.rooms[0].outline) == pytest.approx(0)
    assert max(point[0] for point in converted.plan.rooms[0].outline) == pytest.approx(4_000)
    assert min(point[0] for point in converted.plan.rooms[1].outline) == pytest.approx(4_000)
    assert max(point[0] for point in converted.plan.rooms[1].outline) == pytest.approx(7_000)


def test_roomplan_structure_rejects_overlapping_rooms() -> None:
    structure = RoomPlanStructureCapture.model_validate(
        {
            "structure_id": "home-1",
            "coordinate_space": "shared_arkit_world",
            "rooms": [structure_room("kitchen", 0, 4), structure_room("hall", 3, 7)],
        }
    )

    with pytest.raises(ValueError, match="overlap"):
        floor_plan_from_room_plan_structure(structure, plan_id="home-plan", name="Home")


def test_roomplan_structure_projects_a_second_floor_in_the_shared_frame() -> None:
    structure = RoomPlanStructureCapture.model_validate(
        {
            "structure_id": "home-1",
            "coordinate_space": "shared_arkit_world",
            "rooms": [structure_room("ground", 0, 4), structure_room("upper", 0, 4, 3)],
        }
    )

    converted = floor_plan_from_room_plan_structure(structure, plan_id="home-plan", name="Home")

    assert [level.elevation_mm for level in converted.levels] == [0, 3_000]
    assert converted.levels[0].plan.rooms[0].outline == converted.levels[1].plan.rooms[0].outline
