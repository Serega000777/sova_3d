"""T-156/T-157 (F-035/F-036): the catalogue knows the board; the generator writes a plan the
kernel can build — tray on standoffs, ports open, lid that drops in."""

from __future__ import annotations

from typing import Any

import pytest

from app.engineering import components, enclosure
from app.engineering import knowledge as kb
from app.geometry.operations import parse_plan

# --- F-035: component intelligence -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "component_id"),
    [
        ("корпус под Raspberry Pi 4 с вентилятором", "raspberry-pi-4b"),
        ("a case for the pi 5", "raspberry-pi-5"),
        ("box for arduino mega please", "arduino-mega-2560"),  # not the plain Uno alias
        ("коробка для ардуино уно", "arduino-uno-r3"),
        ("housing for my esp32 devkit", "esp32-devkitc"),
        ("держатель 18650", "holder-18650"),
        ("nothing named here", None),
    ],
)
def test_the_longest_alias_names_the_component(text: str, component_id: str | None) -> None:
    found = components.find(text)
    assert (found.id if found else None) == component_id


def test_every_entry_is_self_consistent() -> None:
    for c in components.COMPONENTS.values():
        assert c.width_mm > 0 and c.depth_mm > 0 and c.thickness_mm > 0
        for hole in c.holes:
            if c.kind in enclosure.HOUSED_KINDS:  # holes lie on the board
                assert 0 < hole.x_mm < c.width_mm and 0 < hole.y_mm < c.depth_mm
            else:  # a servo's ears stick out past its body; a fan's holes are in its frame
                assert -5 < hole.x_mm < c.width_mm + 5 and -5 < hole.y_mm < c.depth_mm + 5
            assert 0 < hole.diameter_mm < 8
        for cut in c.cutouts:  # ports lie along their edge
            along = c.width_mm if cut.side in ("+y", "-y") else c.depth_mm
            assert 0 <= cut.offset_mm and cut.offset_mm + cut.width_mm <= along + 0.01, cut
        assert c.confidence in ("datasheet", "measured", "approximate")
        assert c.note_en and c.note_ru


def test_search_matches_every_word_against_names_aliases_and_tags() -> None:
    assert [c.id for c in components.search("pi")] == [
        "raspberry-pi-4b",
        "raspberry-pi-5",
        "raspberry-pi-zero-2w",
        "raspberry-pi-pico",
    ]
    assert [c.id for c in components.search("fan 40")] == ["fan-40"]
    assert components.search("") == list(components.COMPONENTS.values())
    assert components.search("teapot") == []


def test_describe_speaks_both_languages() -> None:
    pi = components.COMPONENTS["raspberry-pi-4b"]
    en, ru = components.describe(pi, "en"), components.describe(pi, "ru")
    assert en["size_mm"] == [85.0, 56.0, 1.5] and len(en["holes"]) == 4
    assert en["note"] != ru["note"] and "USB" in ru["note"]
    assert {c["name"] for c in en["cutouts"]} >= {"Ethernet", "USB-C power", "microSD"}


# --- F-036: the generator ----------------------------------------------------------------------


def ops_of(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parsed = parse_plan(plan)  # the plan validates as any AI plan would
    return {op.id: op.model_dump(mode="json") for op in parsed.operations}


def test_pi4_case_has_walls_posts_ports_and_a_lid_with_a_fan() -> None:
    built = enclosure.build(
        enclosure.EnclosureRequest(component_id="raspberry-pi-4b", fan_id="fan-40")
    )
    # 85 x 56 board + 1 mm clearance + 2 mm walls; 5 standoff + 1.5 pcb + 16 ports + 2 headroom
    assert built.outer_mm == (91.0, 62.0, 26.5)
    assert built.inner_mm == (87.0, 58.0, 24.5)
    assert built.posts == 4 and built.lid and built.fan == "fan-40"
    assert built.plan["expected_outputs"] == ["tray", "lid"]
    ops = ops_of(built.plan)
    # hollow first, round the outer vertical edges after
    ids = list(ops)
    assert ids.index("hollow") < ids.index("soften")
    assert ops["hollow"]["open_face"] == {"kind": "face_by_normal", "axis": "z", "sign": "+"}
    assert ops["soften"]["edges"]["outer"] is True
    # every post is drilled for the board's M2.5 and fused into the floor
    posts = [op for op in ops.values() if op["type"] == "create_cylinder" and "post" in op["id"]]
    assert len(posts) == 4 and all(op["origin_mm"][2] == 1.5 for op in posts)  # 2 - 0.5 embed
    threads = [op for op in ops.values() if op["type"] == "add_hole"]
    m25_tap = kb.hole_for(kb.FASTENERS["m2.5"], "tap", None)  # 2.2 + what PLA closes up
    assert {op["diameter_mm"] for op in threads if op["id"].startswith("thread")} == {m25_tap}
    assert all(
        op["op"] == "fuse" and op["target"] == "tray"
        for op in ops.values()
        if op["id"].startswith("join_") and op["id"] != "join_lip"
    )
    # ports: one cut per cutout that reaches an outer wall
    ports = [op for op in ops.values() if op["id"].startswith("port_")]
    assert len(ports) == len(components.COMPONENTS["raspberry-pi-4b"].cutouts)
    assert len(built.cutouts) == len(ports)
    # the lid: a plate next to the tray, lip ring, fan opening and its four screws
    assert ops["lid"]["type"] == "create_box" and ops["lid"]["origin_mm"][0] >= 91 + 10
    assert ops["open_fan"]["op"] == "cut" and ops["open_fan"]["target"] == "lid"
    fan_screws = [op for op in threads if op["target"] == "lid"]
    assert len(fan_screws) == 4


def test_without_a_fan_the_lid_gets_vent_slots_and_without_a_lid_nothing() -> None:
    vented = enclosure.build(enclosure.EnclosureRequest(component_id="arduino-uno-r3"))
    ops = ops_of(vented.plan)
    slots = [op for op in ops.values() if op["type"] == "create_box" and "vent_" in op["id"]]
    cuts = [op for op in ops.values() if op["id"].startswith("vent_cut_")]
    assert len(slots) == len(cuts) == 5 and vented.fan is None
    assert all(op["op"] == "cut" and op["target"] == "lid" for op in cuts)
    assert vented.plan["expected_outputs"] == ["tray", "lid"]

    bare = enclosure.build(
        enclosure.EnclosureRequest(component_id="raspberry-pi-zero-2w", lid=False, vents=False)
    )
    ops = ops_of(bare.plan)
    assert "lid" not in ops and bare.plan["expected_outputs"] == ["tray"]
    assert bare.lid is False


def test_a_display_shows_through_a_window_in_its_lid() -> None:
    oled = enclosure.build(enclosure.EnclosureRequest(component_id="oled-096"))
    ops = ops_of(oled.plan)
    assert ops["open_window"]["op"] == "cut" and ops["open_window"]["target"] == "lid"
    window = ops["window"]
    assert (window["width_mm"], window["depth_mm"]) == (23.0, 12.5)  # 22 x 11.5 glass + 1 mm
    assert not any(op["id"].startswith("vent_") for op in ops.values())
    assert "display window" in oled.cutouts
    assert any("approximate" in note for note in oled.notes)


def test_a_thicker_wall_and_no_corner_radius_change_the_plan_not_the_board() -> None:
    thick = enclosure.build(
        enclosure.EnclosureRequest(component_id="esp32-devkitc", wall_mm=3.0, corner_radius_mm=0)
    )
    ops = ops_of(thick.plan)
    assert ops["hollow"]["thickness_mm"] == 3.0 and "soften" not in ops
    esp = components.COMPONENTS["esp32-devkitc"]
    assert thick.outer_mm[0] == esp.width_mm + 2 * 1.0 + 2 * 3.0


def test_unknown_parts_are_refused_before_any_plan_exists() -> None:
    with pytest.raises(KeyError):
        enclosure.build(enclosure.EnclosureRequest(component_id="teapot"))
    with pytest.raises(KeyError):
        enclosure.build(enclosure.EnclosureRequest(component_id="arduino-nano", fan_id="fan-80"))


def test_tap_diameter_prefers_the_knowledge_base_then_the_hole_minus_a_thread() -> None:
    shrink = kb.material(None).hole_undersize_mm  # PLA when nothing was asked for
    assert enclosure.tap_diameter("M2.5", 2.7, None) == round(2.2 + shrink, 2)
    assert enclosure.tap_diameter("M3", 3.2, "petg") == round(
        2.7 + kb.material("petg").hole_undersize_mm, 2
    )
    assert enclosure.tap_diameter("M9", 9.4, None) == pytest.approx(9.1)  # not in the KB


# --- the sentence ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "Сделай корпус под Raspberry Pi 4 с вентилятором 40 мм",
            ("raspberry-pi-4b", "fan-40", True, 2.0),
        ),
        ("коробка для ардуино уно без крышки", ("arduino-uno-r3", None, False, 2.0)),
        (
            "an enclosure for the pi zero 2 w, walls 3 mm, with a 30mm fan",
            ("raspberry-pi-zero-2w", "fan-30", True, 3.0),
        ),
        ("a case for my esp32 with fan 30", ("esp32-devkitc", "fan-30", True, 2.0)),
        ("housing for arduino nano, wall 2.5 mm", ("arduino-nano", None, True, 2.5)),
        ("Box 80x60x40 mm", None),  # no component: the planner's business
        ("a case for a 40 mm fan", None),  # a fan is not a thing to build a case around
        ("корпус", None),
    ],
)
def test_parse_reads_the_component_the_fan_the_lid_and_the_wall(
    prompt: str, expected: tuple[str, str | None, bool, float] | None
) -> None:
    parsed = enclosure.parse(prompt)
    if expected is None:
        assert parsed is None
        return
    assert parsed is not None
    assert (parsed.component_id, parsed.fan_id, parsed.lid, parsed.wall_mm) == expected


# --- F-035 in an edit: the component's hole pattern on an existing plate --------------------


def plate_history(width: float, depth: float) -> list[dict[str, object]]:
    return [
        {
            "id": "plate",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": width,
            "depth_mm": depth,
            "height_mm": 4,
        }
    ]


def test_mounting_holes_follow_the_boards_pattern_centred_on_the_plate() -> None:
    from app.ai.contract import PlanRequest
    from app.ai.planner import StubPlanner, plan_with_repair

    outcome = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="Сделай отверстия под Raspberry Pi 4",
            current_operations=plate_history(100, 70),
            selection_entity_ids=["plate"],
        ),
    )
    assert outcome.status == "planned", outcome
    assert outcome.plan is not None
    holes = [op.model_dump() for op in outcome.plan.operations if op.type == "add_hole"]
    assert len(holes) == 4  # the Pi's four M2.5 holes, 58 x 49 mm apart
    xs = sorted({h["position_mm"][0] for h in holes})
    ys = sorted({h["position_mm"][1] for h in holes})
    assert xs[1] - xs[0] == 58 and ys[1] - ys[0] == 49
    # the board sits centred on the 100 x 70 plate: its corner at (7.5, 7), holes 3.5 mm in
    assert xs[0] == 7.5 + 3.5 and ys[0] == 7 + 3.5
    clearance = kb.hole_for(kb.FASTENERS["m2.5"], "clearance", None)
    assert {h["diameter_mm"] for h in holes} == {clearance}
    assert any("Raspberry Pi 4" in a for a in outcome.plan.assumptions)

    too_small = plan_with_repair(
        StubPlanner(),
        PlanRequest(
            prompt="mounting holes for an arduino mega",
            current_operations=plate_history(60, 40),
            selection_entity_ids=["plate"],
        ),
    )
    assert too_small.status == "needs_clarification"
    assert any("bigger than" in q for q in too_small.clarifications)
