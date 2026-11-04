from copy import deepcopy

import pytest

from app.engineering.room_plan import (
    RoomPlanCapture,
    RoomPlanStructureCapture,
    floor_plan_from_room_plan,
    floor_plan_from_room_plan_structure,
)
from app.engineering.room_shell import (
    RoomShellStructureSpec,
    build_room_shell_plan,
    build_room_shell_structure_plan,
    room_shell_spec,
    room_shell_structure_spec,
)


def payload(schema_version: int = 2) -> dict[str, object]:
    transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1.35, 0, 1]
    wall = {"transform_m": transform, "dimensions_m": [4, 2.7, 0.12]}
    opening = {
        "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 1.05, 0, 1],
        "dimensions_m": [0.9, 2.1, 0.12],
    }
    return {
        "schema_version": schema_version,
        "room_id": "room",
        "walls": [
            {"identifier": "s", "a_m": [0, 0], "b_m": [4, 0], "height_m": 2.7, **wall},
            {
                "identifier": "e",
                "a_m": [4, 0],
                "b_m": [4, 3],
                "height_m": 2.7,
                **wall,
                "dimensions_m": [3, 2.7, 0.12],
            },
            {"identifier": "n", "a_m": [4, 3], "b_m": [0, 3], "height_m": 2.7, **wall},
            {
                "identifier": "w",
                "a_m": [0, 3],
                "b_m": [0, 0],
                "height_m": 2.7,
                **wall,
                "dimensions_m": [3, 2.7, 0.12],
            },
        ],
        "openings": [
            {
                "identifier": "door",
                "parent_wall_id": "s",
                "center_m": [2, 0],
                "width_m": 0.9,
                "kind": "door",
                **opening,
            }
        ],
    }


def structure_room(room_id: str, x_offset: float) -> RoomPlanCapture:
    value = deepcopy(payload())
    value["room_id"] = room_id
    value["floor_elevation_m"] = 0
    wall_ids: dict[str, str] = {}
    for wall in value["walls"]:  # type: ignore[union-attr]
        old_id = wall["identifier"]
        wall["identifier"] = f"{room_id}-{old_id}"
        wall_ids[old_id] = wall["identifier"]
        wall["a_m"][0] += x_offset
        wall["b_m"][0] += x_offset
        wall["transform_m"][12] += x_offset
    for opening in value["openings"]:  # type: ignore[union-attr]
        opening["identifier"] = f"{room_id}-{opening['identifier']}"
        opening["parent_wall_id"] = wall_ids[opening["parent_wall_id"]]
        opening["center_m"][0] += x_offset
        opening["transform_m"][12] += x_offset
    return RoomPlanCapture.model_validate(value)


def test_v2_roomplan_builds_bounded_exact_shell_plan() -> None:
    capture = RoomPlanCapture.model_validate(payload())
    converted = floor_plan_from_room_plan(capture, plan_id="plan", name="Room")
    spec = room_shell_spec(capture, converted)
    assert spec is not None
    assert spec.openings[0].bottom_mm == pytest.approx(0)
    plan = build_room_shell_plan(spec)
    assert plan.expected_outputs == ["floor"]
    assert len(plan.operations) == 21
    assert [op.type for op in plan.operations].count("cut") == 0
    assert sum(op.type == "boolean" and op.op == "cut" for op in plan.operations) == 1


def test_same_width_openings_keep_their_own_measured_lineage() -> None:
    value = payload()
    second = dict(value["openings"][0])  # type: ignore[index]
    second.update(
        identifier="door-2",
        center_m=[3, 0],
        transform_m=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 1.05, 0, 1],
    )
    value["openings"].append(second)  # type: ignore[union-attr]
    capture = RoomPlanCapture.model_validate(value)
    converted = floor_plan_from_room_plan(capture, plan_id="plan", name="Room")
    spec = room_shell_spec(capture, converted)
    assert spec is not None
    assert [opening.offset_mm for opening in spec.openings] == pytest.approx([1_550, 2_550])


def test_v1_roomplan_never_claims_an_empty_shell() -> None:
    legacy = payload(1)
    for surface in [*legacy["walls"], *legacy["openings"]]:  # type: ignore[index,union-attr]
        surface.pop("transform_m")
        surface.pop("dimensions_m")
    capture = RoomPlanCapture.model_validate(legacy)
    converted = floor_plan_from_room_plan(capture, plan_id="plan", name="Room")
    assert room_shell_spec(capture, converted) is None


def test_v2_rejects_missing_full_transform() -> None:
    invalid = payload()
    invalid["walls"][0].pop("transform_m")  # type: ignore[index,union-attr]
    with pytest.raises(ValueError, match="4x4 transform"):
        RoomPlanCapture.model_validate(invalid)


def test_v2_rejects_a_collapsed_transform_basis() -> None:
    invalid = payload()
    invalid["walls"][0]["transform_m"][0] = 0  # type: ignore[index]
    with pytest.raises(ValueError, match="orthonormal"):
        RoomPlanCapture.model_validate(invalid)


def test_structure_builds_one_bounded_plan_from_two_exact_room_loops() -> None:
    capture = RoomPlanStructureCapture(
        structure_id="home",
        coordinate_space="shared_arkit_world",
        rooms=[structure_room("kitchen", 0), structure_room("hall", 4)],
    )
    converted = floor_plan_from_room_plan_structure(capture, plan_id="home", name="Home")

    spec = room_shell_structure_spec(capture, converted)
    restored = RoomShellStructureSpec.from_dict(spec.to_dict())
    plan = build_room_shell_structure_plan(restored)

    assert len(restored.rooms) == 2
    assert len(plan.operations) == 43
    assert len({operation.id for operation in plan.operations}) == len(plan.operations)
    assert plan.expected_outputs == ["room_0_floor"]
    assert any(operation.id == "join_room_1_shell" for operation in plan.operations)


def test_structure_shell_accepts_the_operation_budget_max_and_rejects_the_next_room() -> None:
    room = room_shell_spec(
        structure_room("room", 0),
        floor_plan_from_room_plan(structure_room("room", 0), plan_id="room", name="Room"),
    )
    assert room is not None
    bounded = RoomShellStructureSpec(tuple(room for _ in range(11)))
    oversized = RoomShellStructureSpec(tuple(room for _ in range(12)))

    plan = build_room_shell_structure_plan(bounded)

    assert len(plan.operations) == 241

    with pytest.raises(ValueError, match="operation limit"):
        build_room_shell_structure_plan(oversized)
