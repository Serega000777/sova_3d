"""House inputs produce a stable, editable 2D plan in millimetres."""

import pytest
from pydantic import ValidationError

from app.engineering.floor_plan import (
    FloorPlan,
    PlanRoom,
    PlanWall,
    _classify_outline,
    auto_layout_plan,
    auto_layout_rectangular_plan,
    floor_plan_from_house_box,
    floor_plan_from_house_walls,
)
from app.engineering.house_box import HouseBoxRequest
from app.engineering.house_walls import HouseWallsRequest, PlanWallInput


def _area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            x * points[(index + 1) % len(points)][1] - points[(index + 1) % len(points)][0] * y
            for index, (x, y) in enumerate(points)
        )
        / 2
    )


def _plan_from_outline(outline: list[tuple[float, float]], *, plan_id: str = "plan") -> FloorPlan:
    return FloorPlan(
        id=plan_id,
        name="House",
        walls=[
            PlanWall(a=point, b=outline[(index + 1) % len(outline)], thickness_mm=120)
            for index, point in enumerate(outline)
        ],
        rooms=[PlanRoom(name="Footprint", outline=outline)],
    )


def _house_box_plan(shape: str, *, length: float = 12_000, width: float = 8_000) -> FloorPlan:
    return floor_plan_from_house_box(
        HouseBoxRequest(
            length_mm=length,
            width_mm=width,
            floor_height_mm=3_000,
            floors=1,
            shape=shape,  # type: ignore[arg-type]
        ),
        plan_id=f"{shape}-plan",
        name="House",
    )


@pytest.mark.parametrize(
    ("shape", "corners", "area_mm2"),
    [
        ("rectangle", 4, 96_000_000),
        ("l_shape", 6, 72_000_000),
        ("t_shape", 8, 160_000_000 / 3),
    ],
)
def test_house_box_projects_its_real_footprint(shape: str, corners: int, area_mm2: float) -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=2,
        shape=shape,  # type: ignore[arg-type]
    )
    plan = floor_plan_from_house_box(request, plan_id="house-floor-1", name="House")

    assert plan.id == "house-floor-1"
    assert len(plan.walls) == corners
    assert len(plan.rooms[0].outline) == corners
    assert _area(plan.rooms[0].outline) == pytest.approx(area_mm2)


def test_freeform_walls_are_ordered_into_one_room_even_when_edges_are_shuffled() -> None:
    request = HouseWallsRequest(
        walls=[
            PlanWallInput(a=(6_000, 4_000), b=(0, 4_000)),
            PlanWallInput(a=(0, 0), b=(6_000, 0)),
            PlanWallInput(a=(0, 4_000), b=(0, 0)),
            PlanWallInput(a=(6_000, 0), b=(6_000, 4_000)),
        ],
        floor_height_mm=3_000,
        floors=1,
    )
    plan = floor_plan_from_house_walls(request, plan_id="drawn-floor-1", name="Drawn house")

    assert len(plan.walls) == 4
    assert _area(plan.rooms[0].outline) == pytest.approx(24_000_000)


def test_disconnected_closed_loops_are_not_accepted_as_one_house() -> None:
    first = [(0.0, 0.0), (3_000.0, 0.0), (1_500.0, 2_600.0)]
    second = [(10_000.0, 0.0), (13_000.0, 0.0), (11_500.0, 2_600.0)]
    walls = [
        PlanWallInput(a=polygon[index], b=polygon[(index + 1) % 3])
        for polygon in (first, second)
        for index in range(3)
    ]

    with pytest.raises(ValidationError, match="single connected loop"):
        HouseWallsRequest(walls=walls, floor_height_mm=3_000, floors=1)


def test_rectangular_house_gets_connected_rooms_and_internal_doors() -> None:
    request = HouseBoxRequest(
        length_mm=12_000,
        width_mm=8_000,
        floor_height_mm=3_000,
        floors=1,
        shape="rectangle",
    )
    source = floor_plan_from_house_box(request, plan_id="house-floor-1", name="House")

    plan = auto_layout_rectangular_plan(source, room_count=3)

    assert plan.id == source.id and len(plan.rooms) == 3
    assert [_area(room.outline) for room in plan.rooms] == [32_000_000] * 3
    assert len(plan.walls) == 6
    assert len(plan.openings) == 2
    assert [opening.wall for opening in plan.openings] == [4, 5]
    assert all(opening.kind == "door" and opening.width_mm == 900 for opening in plan.openings)

    revised = auto_layout_rectangular_plan(plan, room_count=2)
    assert len(revised.rooms) == 2
    assert len(revised.walls) == 5
    assert [opening.wall for opening in revised.openings] == [4]


def test_auto_layout_refuses_irregular_or_impossibly_small_footprints() -> None:
    irregular = _house_box_plan("l_shape")
    small = floor_plan_from_house_box(
        HouseBoxRequest(
            length_mm=4_000,
            width_mm=4_000,
            floor_height_mm=3_000,
            floors=1,
            shape="rectangle",
        ),
        plan_id="small-plan",
        name="Small house",
    )

    with pytest.raises(ValueError, match="axis-aligned rectangle"):
        auto_layout_rectangular_plan(irregular, room_count=3)
    with pytest.raises(ValueError, match="too small"):
        auto_layout_rectangular_plan(small, room_count=3)


def test_reflex_classification_and_exact_decomposition_are_rotation_independent() -> None:
    assert _classify_outline(_house_box_plan("rectangle").rooms[0].outline) is None

    l_shape = _classify_outline(_house_box_plan("l_shape").rooms[0].outline)
    assert l_shape is not None and l_shape.shape == "l_shape"
    assert l_shape.seam == ((6_000, 4_000), (0, 4_000))
    assert set(l_shape.zones) == {
        (0, 4_000, 6_000, 8_000),
        (0, 0, 12_000, 4_000),
    }

    t_shape = _classify_outline(_house_box_plan("t_shape").rooms[0].outline)
    assert t_shape is not None and t_shape.shape == "t_shape"
    assert t_shape.seam == ((4_000, 16_000 / 3), (8_000, 16_000 / 3))
    assert set(t_shape.zones) == {
        (0, 16_000 / 3, 12_000, 8_000),
        (4_000, 0, 8_000, 16_000 / 3),
    }

    mirrored = [
        (0.0, 0.0),
        (0.0, 10_000.0),
        (10_000.0, 10_000.0),
        (10_000.0, 6_000.0),
        (4_000.0, 6_000.0),
        (4_000.0, 0.0),
    ]
    mirrored_request = HouseWallsRequest(
        walls=[
            PlanWallInput(a=point, b=mirrored[(index + 1) % len(mirrored)])
            for index, point in enumerate(mirrored)
        ],
        floor_height_mm=3_000,
        floors=1,
    )
    mirrored_plan = floor_plan_from_house_walls(
        mirrored_request, plan_id="mirrored-l", name="Mirrored L"
    )
    mirrored_shape = _classify_outline(mirrored_plan.rooms[0].outline)
    assert mirrored_shape is not None and mirrored_shape.shape == "l_shape"
    assert sum(
        (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) for bounds in mirrored_shape.zones
    ) == pytest.approx(_area(mirrored))


@pytest.mark.parametrize(
    ("shape", "room_count", "outer_wall_count"),
    [("l_shape", 4, 7), ("t_shape", 5, 8)],
)
def test_l_and_t_layouts_cover_the_footprint_and_connect_every_partition(
    shape: str, room_count: int, outer_wall_count: int
) -> None:
    source = _house_box_plan(shape)
    result = auto_layout_plan(source, room_count=room_count)
    plan = result.plan

    assert result.kind == "lt_decomposition_v1"
    assert sum(result.zone_room_counts or ()) == room_count
    assert len(plan.rooms) == room_count
    assert sum(_area(room.outline) for room in plan.rooms) == pytest.approx(
        _area(source.rooms[0].outline)
    )
    partition_indices = set(range(outer_wall_count, len(plan.walls)))
    assert {opening.wall for opening in plan.openings} == partition_indices
    assert len(plan.openings) == len(partition_indices)
    seam = plan.walls[-1]
    seam_length = ((seam.b[0] - seam.a[0]) ** 2 + (seam.b[1] - seam.a[1]) ** 2) ** 0.5
    assert plan.openings[-1].wall == len(plan.walls) - 1
    assert plan.openings[-1].offset_mm == pytest.approx((seam_length - 900) / 2)

    revised = auto_layout_plan(plan, room_count=room_count - 1)
    assert revised.kind == "lt_decomposition_v1"
    assert len(revised.plan.rooms) == room_count - 1
    assert sum(_area(room.outline) for room in revised.plan.rooms) == pytest.approx(
        _area(source.rooms[0].outline)
    )


def test_l_layout_splits_the_far_exterior_wall_at_the_seam() -> None:
    source = _house_box_plan("l_shape")
    result = auto_layout_plan(source, room_count=4)

    assert len(source.walls) == 6
    assert len([wall for wall in result.plan.walls[:7] if wall.a[0] == wall.b[0] == 0]) == 2
    assert {point for wall in result.plan.walls[:7] for point in (wall.a, wall.b)} >= {
        (0.0, 4_000.0)
    }


@pytest.mark.parametrize(
    ("shape", "room_count", "expected_offset", "crossing_offsets"),
    [
        ("l_shape", 5, 3_260.0, [2_000.0, 3_000.0]),
        ("t_shape", 4, 840.0, [2_000.0]),
    ],
)
def test_seam_door_avoids_strip_partitions_with_required_clearance(
    shape: str,
    room_count: int,
    expected_offset: float,
    crossing_offsets: list[float],
) -> None:
    result = auto_layout_plan(_house_box_plan(shape), room_count=room_count)
    seam_door = result.plan.openings[-1]

    assert seam_door.wall == len(result.plan.walls) - 1
    assert seam_door.offset_mm == pytest.approx(expected_offset)
    door_start = seam_door.offset_mm
    door_end = door_start + seam_door.width_mm
    for crossing in crossing_offsets:
        assert min(abs(crossing - door_start), abs(crossing - door_end)) >= 260.0 - 1e-6


def test_auto_layout_rejects_every_shape_outside_the_l_t_boundary() -> None:
    non_collinear_reflex = _plan_from_outline(
        [
            (0, 0),
            (10_000, 0),
            (10_000, 3_000),
            (7_000, 3_000),
            (7_000, 7_000),
            (3_000, 7_000),
            (3_000, 10_000),
            (0, 10_000),
        ]
    )
    cross = _plan_from_outline(
        [
            (3_000, 0),
            (6_000, 0),
            (6_000, 3_000),
            (9_000, 3_000),
            (9_000, 6_000),
            (6_000, 6_000),
            (6_000, 9_000),
            (3_000, 9_000),
            (3_000, 6_000),
            (0, 6_000),
            (0, 3_000),
            (3_000, 3_000),
        ]
    )
    diagonal = _plan_from_outline([(0, 0), (8_000, 0), (4_000, 6_000)])

    with pytest.raises(ValueError, match="reflex corners don't form a single L or T seam"):
        auto_layout_plan(non_collinear_reflex, room_count=3)
    with pytest.raises(ValueError, match="supports rectangle, L and T footprints only"):
        auto_layout_plan(cross, room_count=4)
    with pytest.raises(ValueError, match="requires an axis-aligned footprint"):
        auto_layout_plan(diagonal, room_count=2)


def test_auto_layout_rejects_undersized_zones_and_seams_with_specific_errors() -> None:
    zone_too_small = _house_box_plan("l_shape", length=6_000, width=4_000)
    short_seam = _plan_from_outline(
        [
            (0, 0),
            (2_000, 0),
            (2_000, 1_000),
            (1_000, 1_000),
            (1_000, 2_000),
            (0, 2_000),
        ]
    )

    with pytest.raises(ValueError, match="too small for that many rooms"):
        auto_layout_plan(zone_too_small, room_count=5)
    with pytest.raises(ValueError) as error:
        auto_layout_plan(short_seam, room_count=2)
    assert str(error.value) == " ".join(
        ("the seam between the two parts of the house is too short for the requested", "door width")
    )

    fragmented_seam = _house_box_plan("t_shape", length=6_600, width=6_000)
    with pytest.raises(ValueError) as error:
        auto_layout_plan(
            fragmented_seam,
            room_count=4,
            door_width_mm=1_600,
        )
    assert str(error.value) == "the seam has no collision-free span for the requested door width"
