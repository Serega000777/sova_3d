"""T-116 (F-005): the numbers the engineering assistant cites are rules, not guesses."""

from __future__ import annotations

import pytest

from app.engineering import knowledge as kb


def test_walls_grow_with_the_job_and_the_material() -> None:
    assert kb.recommended_wall_mm("pla", "cosmetic") < kb.recommended_wall_mm("pla", "structural")
    assert kb.recommended_wall_mm("pla", "structural") < kb.recommended_wall_mm(
        "pla", "load_bearing"
    )
    # TPU is soft, so it needs more wall for the same job than PLA
    assert kb.recommended_wall_mm("tpu", "structural") > kb.recommended_wall_mm("pla", "structural")


def test_walls_are_whole_extrusion_lines() -> None:
    line = kb.DEFAULT_NOZZLE_MM * kb.LINE_FACTOR
    for material_id in kb.MATERIALS:
        for load in kb.LOADS:
            wall = kb.recommended_wall_mm(material_id, load)
            assert wall / line == pytest.approx(round(wall / line), abs=1e-6)
            assert wall >= 2 * line
    # a bigger nozzle lays wider lines, so the wall rounds up to them
    assert kb.recommended_wall_mm("pla", "structural", nozzle_mm=0.6) >= kb.recommended_wall_mm(
        "pla", "structural"
    )


def test_holes_for_screws_come_out_right_in_plastic() -> None:
    m5 = kb.FASTENERS["m5"]
    assert kb.hole_for(m5, "clearance", "pla") == pytest.approx(5.7)  # 5.5 + PLA undersize
    assert kb.hole_for(m5, "tap", "pla") < m5.nominal_mm  # the screw must bite
    assert kb.hole_for(m5, "heat_set", "pla") > m5.nominal_mm
    # stringier materials close holes more, so the model asks for a little extra
    assert kb.hole_for(m5, "clearance", "petg") > kb.hole_for(m5, "clearance", "pla")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("сделай отверстие под М5", "M5"),
        ("holes for m3 screws", "M3"),
        ("under M2.5 inserts", "M2.5"),
        ("a 6 mm hole", None),
    ],
)
def test_fasteners_are_found_in_either_language(text: str, expected: str | None) -> None:
    found = kb.fastener_for(text)
    assert (found.name if found else None) == expected


def test_fits_add_room_except_a_press_fit() -> None:
    assert kb.fit_allowance_mm("clearance", "pla") > kb.fit_allowance_mm("sliding", "pla")
    assert kb.fit_allowance_mm("sliding", "pla") > kb.fit_allowance_mm("transition", "pla")
    assert kb.fit_allowance_mm("press", "pla") < 0
    assert kb.fit_allowance_mm("sliding", "petg") > kb.fit_allowance_mm("sliding", "pla")


def test_material_ranking_follows_the_purpose() -> None:
    outdoor = kb.rank_materials(kb.purpose_words("держатель для садового шланга на улице"))
    assert outdoor[0][0].id == "asa"
    assert [known.id for known, _, _ in outdoor].index("pla") > 0
    flexible = kb.rank_materials(kb.purpose_words("a soft bumper that bends"))
    assert flexible[0][0].id == "tpu"
    plain = kb.rank_materials(kb.purpose_words("a pen holder for my desk"))
    assert plain[0][0].id == "pla"  # nothing special asked: the easy material wins


def test_unknown_material_falls_back_to_pla_without_lying() -> None:
    assert kb.material("unobtainium").id == "pla"
    assert kb.material(None).id == "pla"
