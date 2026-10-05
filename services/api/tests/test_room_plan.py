import pytest

from app.engineering.room_plan import RoomPlanCapture, floor_plan_from_room_plan


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
                "kind": "door",
            },
            {
                "identifier": "window-1",
                "parent_wall_id": None,
                "center_m": (4.0, 1.5),
                "width_m": 1.2,
                "kind": "window",
            },
            {
                "identifier": "passage-1",
                "parent_wall_id": "west",
                "center_m": (0, 1.5),
                "width_m": 1.0,
                "kind": "opening",
            },
        ],
    }
    payload.update(updates)
    return RoomPlanCapture.model_validate(payload)


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
    assert converted.warnings == ()


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
