"""T-118 (F-005): the engineer's answers come from the facts and the rules, in either language."""

from __future__ import annotations

from typing import Any

import pytest

from app.engineering import assistant
from app.engineering.assistant import Facts, WallStats, build_report


def facts(*, p5: float = 1.2, region: float | None = None, slender: float = 10.0) -> Facts:
    walls = WallStats(
        samples=400,
        min_mm=p5 - 0.1,
        p5_mm=p5,
        median_mm=p5 + 0.3,
        max_mm=30,
        limit_mm=1.6,
        thin_fraction=0.4 if p5 < 1.6 else 0.0,
    )
    region_walls = (
        None
        if region is None
        else WallStats(
            samples=40,
            min_mm=region,
            p5_mm=region,
            median_mm=region,
            max_mm=region,
            limit_mm=1.6,
            thin_fraction=1.0 if region < 1.6 else 0.0,
        )
    )
    return Facts(
        bbox_mm=[60, 40, 30],
        volume_mm3=11358.7,
        watertight=True,
        faces=28,
        walls=walls,
        region_walls=region_walls,
        region_faces=0 if region is None else 4,
        slenderness=slender,
        mass_g={"pla": 14.08, "petg": 14.43, "abs": 11.81, "tpu": 13.74, "asa": 12.15},
    )


def plan_with_holes() -> list[dict[str, Any]]:
    return [
        {"id": "op_1", "type": "create_box", "width_mm": 60, "depth_mm": 40, "height_mm": 8},
        {
            "id": "op_2",
            "type": "add_hole",
            "target": "op_1",
            "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            "position_mm": [10, 10],
            "diameter_mm": 4.0,
        },
    ]


def ask(question: str, **kwargs: Any) -> assistant.Answer:
    report = build_report(
        facts=kwargs.pop("facts", facts()),
        operations=kwargs.pop("operations", []),
        material_id=kwargs.pop("material_id", "pla"),
        question=question,
        purpose=kwargs.pop("purpose", None),
        region=kwargs.pop("region", None),
    )
    assert report.answer is not None
    return report.answer


def test_a_thin_wall_gets_a_yes_with_the_numbers_in_russian() -> None:
    answer = ask("Эта стенка слишком тонкая?")
    assert answer.intent == "walls" and answer.verdict == "yes" and answer.language == "ru"
    assert "1.2 mm" in answer.summary and "1.8 mm" in answer.summary  # PLA structural = 4 lines
    assert answer.recommendation == "Увеличьте толщину до 1.8 mm."
    assert answer.numbers["measured_mm"] == 1.2
    assert any("сломается" in reason for reason in answer.reasons)  # PLA is brittle


def test_the_same_question_in_english_about_an_outlined_area() -> None:
    region = {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 40, 30]}
    answer = ask("is this wall too thin?", facts=facts(p5=2.0, region=1.2), region=region)
    assert answer.verdict == "yes" and answer.language == "en"
    assert answer.summary.startswith("Yes. In the outlined area: 1.2 mm")
    # the part as a whole is fine; the answer is about the area the user pointed at
    assert answer.numbers["measured_mm"] == 1.2


def test_a_thick_enough_wall_gets_a_no() -> None:
    answer = ask("is the wall thick enough?", facts=facts(p5=2.5))
    assert answer.verdict == "no" and answer.recommendation is None
    assert "2.5 mm" in answer.summary


def test_load_bearing_questions_raise_the_bar() -> None:
    # 2 mm is fine for a structural PLA wall but not for one carrying a load
    assert ask("is the wall thick enough?", facts=facts(p5=2.0)).verdict == "no"
    heavy = ask("will it hold 5 kg?", facts=facts(p5=2.0))
    assert heavy.intent == "strength" and heavy.verdict == "no"
    assert "2.7 mm" in heavy.reasons[0]  # PLA load-bearing = 6 lines
    assert heavy.recommendation is not None and "PETG" in heavy.recommendation
    assert "test" in heavy.summary.lower()


def test_a_slender_part_is_called_a_lever() -> None:
    answer = ask("выдержит?", facts=facts(p5=2.5, slender=40))
    assert answer.verdict == "no"
    assert any("рычаг" in reason for reason in answer.reasons)


def test_material_choice_follows_the_purpose() -> None:
    answer = ask("какой пластик выбрать?", purpose="держатель для садового шланга на улице")
    assert answer.intent == "material"
    assert answer.summary.startswith("ASA")
    assert answer.recommendation == "Печатайте из ASA."
    assert any("Масса детали из ASA: 12.15 г" == reason for reason in answer.reasons)


def test_a_screw_question_names_the_hole_and_offers_the_fix() -> None:
    answer = ask("сделай отверстия под М5", operations=plan_with_holes())
    assert answer.intent == "fastener" and answer.language == "ru"
    assert answer.numbers["diameter_mm"] == pytest.approx(5.7)
    assert answer.fix is not None
    assert answer.fix.operations == [
        {"type": "set_parameter", "operation": "op_2", "parameter": "diameter_mm", "value": 5.7}
    ]


def test_the_review_does_not_repeat_what_the_answer_already_fixes() -> None:
    holes = plan_with_holes()
    holes[1]["diameter_mm"] = 4.9  # odd on its own, and the question is about it
    report = build_report(
        facts=facts(),
        operations=holes,
        material_id="pla",
        question="M5 screws",
        purpose=None,
        region=None,
    )
    assert report.answer is not None and report.answer.fix is not None
    assert all(rec.intent != "fastener" for rec in report.recommendations)


def test_a_screw_that_already_fits_needs_no_fix() -> None:
    holes = plan_with_holes()
    holes[1]["diameter_mm"] = 3.6  # M3 clearance in PLA
    answer = ask("holes for m3 screws", operations=holes)
    assert answer.fix is None
    assert answer.numbers["diameter_mm"] == pytest.approx(3.6)


def test_heat_set_inserts_and_self_tapping_screws_are_different_holes() -> None:
    insert = ask("M3 heat-set insert", operations=[])
    tapping = ask("саморез М3 вкрутить", operations=[])
    passing = ask("m3 screw", operations=[])
    assert insert.numbers["diameter_mm"] > passing.numbers["diameter_mm"]
    assert tapping.numbers["diameter_mm"] < passing.numbers["diameter_mm"]


def test_fit_questions_give_the_allowance() -> None:
    sliding = ask("какой зазор нужен, чтобы деталь скользила?")
    press = ask("what tolerance for a press fit?")
    assert sliding.intent == "fit" and sliding.numbers["allowance_mm"] == pytest.approx(0.3)
    assert press.numbers["allowance_mm"] < 0
    assert "+0.3" in sliding.summary and "−0.15" in press.summary


def test_a_question_the_engineer_does_not_understand_gets_the_facts() -> None:
    answer = ask("what do you think?")
    assert answer.intent == "overview" and answer.verdict == "info"
    assert "60 × 40 × 30 mm" in answer.summary and "14.08 g in PLA" in answer.summary


def test_the_report_flags_thin_walls_and_odd_holes_without_a_question() -> None:
    holes = plan_with_holes()
    holes[1]["diameter_mm"] = 4.9  # nothing takes a 4.9 mm hole
    report = build_report(
        facts=facts(), operations=holes, material_id="pla", question=None, purpose=None, region=None
    )
    assert report.answer is None
    intents = [rec.intent for rec in report.recommendations]
    assert "walls" in intents and "fastener" in intents
    fastener = next(rec for rec in report.recommendations if rec.intent == "fastener")
    assert "M4" in fastener.summary  # the nearest screw size
    assert fastener.fix is not None and fastener.fix.operations[0]["value"] == pytest.approx(4.7)
    assert report.materials[0].id == "pla"  # nothing said about the purpose


def test_the_same_facts_give_the_same_answer() -> None:
    def report() -> assistant.Report:
        return build_report(
            facts=facts(),
            operations=plan_with_holes(),
            material_id="pla",
            question="тонкая?",
            purpose=None,
            region=None,
        )

    assert report() == report()
