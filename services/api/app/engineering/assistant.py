"""The engineer answers (T-118, F-005).

"Эта стенка слишком тонкая?" → "Да. 1.2 мм; при печати PLA вероятно сломается. Лучше
увеличить до 2.5 мм." The verdict comes from measured facts and the knowledge base — the
same question about the same part gets the same answer — and when the fix is a number the
kernel understands (a hole diameter, a dimension), it is returned as operations the edit
endpoint validates like any other plan.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engineering import knowledge as kb

Intent = Literal["walls", "strength", "material", "fastener", "fit", "overview"]
Verdict = Literal["yes", "no", "unsure", "info"]
Language = Literal["ru", "en"]


class WallStats(BaseModel):
    samples: int
    min_mm: float
    p5_mm: float
    median_mm: float
    max_mm: float
    limit_mm: float
    thin_fraction: float


class Facts(BaseModel):
    """What the worker measured (worker.engineering.EngineeringFacts, mirrored here)."""

    ok: bool = True
    message: str | None = None
    bbox_mm: list[float] = Field(default_factory=list)
    volume_mm3: float | None = None
    area_mm2: float | None = None
    watertight: bool = False
    faces: int = 0
    walls: WallStats | None = None
    region_walls: WallStats | None = None
    region_faces: int = 0
    slenderness: float | None = None
    mass_g: dict[str, float] = Field(default_factory=dict)


class Hole(BaseModel):
    """A hole the plan drilled, with what it would take for a screw."""

    operation_id: str
    diameter_mm: float
    through: bool
    fits: dict[str, str] = Field(default_factory=dict)  # "M3": "clearance" ...


class MaterialChoice(BaseModel):
    id: str
    name: str
    score: int
    reasons: list[str]
    note: str
    max_service_c: float
    mass_g: float | None = None


class Fix(BaseModel):
    """Operations for POST /models/{version}/edits — validated before they are offered."""

    label: str
    operations: list[dict[str, Any]]


class Answer(BaseModel):
    intent: Intent
    verdict: Verdict
    language: Language
    summary: str
    reasons: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    numbers: dict[str, float] = Field(default_factory=dict)
    fix: Fix | None = None
    # Rules of thumb are labelled as such: this is how sure the engineer is.
    confidence: Literal["high", "medium", "low"] = "medium"


class Report(BaseModel):
    material_id: str
    load: kb.Load
    recommended_wall_mm: float
    facts: Facts
    holes: list[Hole] = Field(default_factory=list)
    materials: list[MaterialChoice] = Field(default_factory=list)
    recommendations: list[Answer] = Field(default_factory=list)
    answer: Answer | None = None


# --- reading the question ------------------------------------------------------------------

# Russian cues are stems (the ending inflects); Latin cues are whole-word patterns, so
# "thin" does not fire on "think" and "wall" still catches "walls".
CUES: dict[Intent, tuple[str, ...]] = {
    "walls": ("тонк", "толщин", "стенк", r"thin(?:n(?:er|est))?", r"thick(?:er|ness)?", r"walls?"),
    "strength": (
        "сломает",
        "выдерж",
        "прочн",
        "треснет",
        "нагруз",
        r"strong(?:er)?",
        "strength",
        r"break(?:s|ing)?",
        r"holds?",
        r"load(?:s|ed|ing)?",
        r"cracks?",
        r"snaps?",
    ),
    "material": (
        "материал",
        "пластик",
        r"materials?",
        r"plastics?",
        "filament",
        "pla",
        "petg",
        "abs",
        "asa",
        "tpu",
    ),
    "fastener": (
        "винт",
        "болт",
        "саморез",
        "резьб",
        r"screws?",
        r"bolts?",
        r"inserts?",
        r"thread(?:s|ed)?",
    ),
    "fit": (
        "зазор",
        "допуск",
        "посадк",
        "натяг",
        r"tolerances?",
        "clearance",
        r"fits?",
        r"slid(?:e|es|ing)",
        "press",
    ),
}


def language_of(text: str) -> Language:
    return "ru" if re.search(r"[а-яА-ЯёЁ]", text) else "en"


def _has_cue(lowered: str, cue: str) -> bool:
    """Latin cues are whole-word patterns; Russian stems match anywhere in a word."""
    if re.match(r"[a-z]", cue):
        return re.search(r"\b(?:" + cue + r")\b", lowered) is not None
    return cue in lowered


def intent_of(text: str) -> Intent:
    lowered = text.lower()
    if kb.fastener_for(lowered) is not None:
        return "fastener"
    for intent in ("fastener", "fit", "walls", "strength", "material"):
        if any(_has_cue(lowered, cue) for cue in CUES[intent]):
            return intent
    return "overview"


def load_of(text: str, default: kb.Load = "structural") -> kb.Load:
    lowered = text.lower()
    if any(cue in lowered for cue in ("нагруз", "вес", "держать", "load", "weight", "kg", "кг")):
        return "load_bearing"
    if any(cue in lowered for cue in ("декор", "decor", "cosmetic", "внешн", "look")):
        return "cosmetic"
    return default


def fit_of(text: str) -> kb.Fit:
    lowered = text.lower()
    if any(cue in lowered for cue in ("натяг", "press", "tight")):
        return "press"
    if any(cue in lowered for cue in ("плотн", "transition", "snug")):
        return "transition"
    if any(cue in lowered for cue in ("скольз", "slide", "sliding")):
        return "sliding"
    return "clearance"


# --- holes from the plan -------------------------------------------------------------------


def holes_in(operations: list[dict[str, Any]]) -> list[Hole]:
    holes: list[Hole] = []
    for op in operations:
        if op.get("type") != "add_hole":
            continue
        diameter = float(op.get("diameter_mm") or 0)
        hole = Hole(
            operation_id=str(op.get("id")),
            diameter_mm=diameter,
            through=op.get("depth_mm") is None,
        )
        for fastener in kb.FASTENERS.values():
            for use in ("clearance", "tap", "heat_set"):
                if abs(kb.hole_for(fastener, use, None) - diameter) <= 0.15:
                    hole.fits[fastener.name] = use
        holes.append(hole)
    return holes


# --- wording -------------------------------------------------------------------------------


def _mm(value: float) -> str:
    return f"{value:g} mm"


def _walls_answer(
    facts: Facts, report_wall: float, material: kb.MaterialKnowledge, lang: Language, region: bool
) -> Answer:
    stats = facts.region_walls if region and facts.region_walls else facts.walls
    if stats is None:
        return Answer(
            intent="walls",
            verdict="unsure",
            language=lang,
            summary="Не удалось измерить стенки этой модели."
            if lang == "ru"
            else "The walls of this model could not be measured.",
            confidence="low",
        )
    measured = stats.p5_mm if not region else stats.median_mm
    thin = measured < report_wall - 1e-6
    where = (
        ("В выделенной области" if lang == "ru" else "In the outlined area")
        if region and facts.region_walls
        else ("Самые тонкие места" if lang == "ru" else "The thinnest places")
    )
    numbers = {"measured_mm": measured, "recommended_mm": report_wall, "min_mm": stats.min_mm}
    if thin:
        summary = (
            f"Да. {where}: {_mm(measured)} при рекомендуемых {_mm(report_wall)} "
            f"для {material.name}."
            if lang == "ru"
            else f"Yes. {where}: {_mm(measured)} against {_mm(report_wall)} "
            f"recommended for {material.name}."
        )
        reasons = [
            (
                f"{material.name}: {material.note_ru}"
                if lang == "ru"
                else f"{material.name}: {material.note_en}"
            ),
            (
                f"{stats.thin_fraction:.0%} измеренной поверхности тоньше {_mm(stats.limit_mm)}"
                if lang == "ru"
                else f"{stats.thin_fraction:.0%} of the measured surface is thinner "
                f"than {_mm(stats.limit_mm)}"
            ),
        ]
        if material.impact == "low":
            reasons.append(
                "При ударе или изгибе такая стенка вероятно сломается."
                if lang == "ru"
                else "A wall this thin will likely break when knocked or bent."
            )
        recommendation = (
            f"Увеличьте толщину до {_mm(report_wall)}."
            if lang == "ru"
            else f"Increase the wall to {_mm(report_wall)}."
        )
        return Answer(
            intent="walls",
            verdict="yes",
            language=lang,
            summary=summary,
            reasons=reasons,
            recommendation=recommendation,
            numbers=numbers,
            confidence="high" if stats.samples >= 20 else "medium",
        )
    summary = (
        f"Нет. {where}: {_mm(measured)}, рекомендуемый минимум для {material.name} — "
        f"{_mm(report_wall)}."
        if lang == "ru"
        else f"No. {where}: {_mm(measured)}; the recommended minimum for {material.name} "
        f"is {_mm(report_wall)}."
    )
    return Answer(
        intent="walls",
        verdict="no",
        language=lang,
        summary=summary,
        reasons=[
            (
                f"{material.name}: {material.note_ru}"
                if lang == "ru"
                else f"{material.name}: {material.note_en}"
            )
        ],
        numbers=numbers,
        confidence="high" if stats.samples >= 20 else "medium",
    )


def _strength_answer(
    facts: Facts, report_wall: float, material: kb.MaterialKnowledge, lang: Language, load: kb.Load
) -> Answer:
    stats = facts.walls
    reasons: list[str] = []
    verdict: Verdict = "unsure"
    numbers: dict[str, float] = {}
    if stats is not None:
        numbers["walls_p5_mm"] = stats.p5_mm
        numbers["recommended_mm"] = report_wall
        if stats.p5_mm < report_wall:
            verdict = "no"
            reasons.append(
                f"Стенки {_mm(stats.p5_mm)} при рекомендуемых {_mm(report_wall)} под нагрузку."
                if lang == "ru"
                else f"Walls of {_mm(stats.p5_mm)} against {_mm(report_wall)} "
                "recommended for the load."
            )
        else:
            verdict = "yes"
    if facts.slenderness is not None:
        numbers["slenderness"] = facts.slenderness
        if facts.slenderness > kb.SLENDER_RATIO:
            verdict = "no" if verdict != "unsure" else "unsure"
            reasons.append(
                f"Деталь длинная и тонкая (отношение {facts.slenderness:g}): работает как рычаг."
                if lang == "ru"
                else f"The part is long and thin (ratio {facts.slenderness:g}): "
                "it works as a lever."
            )
    if material.impact == "low":
        reasons.append(
            f"{material.name} хрупкий: {material.note_ru}"
            if lang == "ru"
            else f"{material.name} is brittle: {material.note_en}"
        )
    tougher = "petg" if material.id == "pla" else None
    recommendation = None
    if verdict == "no":
        parts = []
        if stats is not None and stats.p5_mm < report_wall:
            parts.append(
                f"увеличьте стенки до {_mm(report_wall)}"
                if lang == "ru"
                else f"increase the walls to {_mm(report_wall)}"
            )
        if tougher:
            parts.append(
                f"или печатайте из {kb.MATERIALS[tougher].name}"
                if lang == "ru"
                else f"or print it in {kb.MATERIALS[tougher].name}"
            )
        joined = ", ".join(parts)
        recommendation = joined[0].upper() + joined[1:] + "." if parts else None
    summary = {
        "yes": "Да, скорее всего выдержит." if lang == "ru" else "Yes, it should hold.",
        "no": "Скорее всего нет." if lang == "ru" else "Probably not.",
        "unsure": "Не уверен: не хватает данных." if lang == "ru" else "Not sure: not enough data.",
        "info": "",
    }[verdict]
    if load == "load_bearing":
        summary += (
            " Расчёт по правилам для нагруженных деталей; для критичных — проверьте испытанием."
            if lang == "ru"
            else " Rules of thumb for load-bearing parts; test a critical part before trusting it."
        )
    return Answer(
        intent="strength",
        verdict=verdict,
        language=lang,
        summary=summary,
        reasons=reasons,
        recommendation=recommendation,
        numbers=numbers,
        confidence="medium" if verdict != "unsure" else "low",
    )


def _material_answer(choices: list[MaterialChoice], lang: Language, purpose: str) -> Answer:
    if not choices:
        return Answer(
            intent="material", verdict="unsure", language=lang, summary="", confidence="low"
        )
    best = choices[0]
    why = (
        ", ".join(best.reasons)
        if best.reasons
        else ("простой в печати" if lang == "ru" else "easy to print")
    )
    summary = (
        f"{best.name}: {why}. {best.note}" if lang == "ru" else f"{best.name}: {why}. {best.note}"
    )
    runner_up = choices[1] if len(choices) > 1 else None
    reasons = []
    if runner_up:
        reasons.append(
            f"Альтернатива — {runner_up.name}: {runner_up.note}"
            if lang == "ru"
            else f"Alternative — {runner_up.name}: {runner_up.note}"
        )
    if best.mass_g is not None:
        reasons.append(
            f"Масса детали из {best.name}: {best.mass_g:g} г"
            if lang == "ru"
            else f"The part weighs {best.mass_g:g} g in {best.name}"
        )
    return Answer(
        intent="material",
        verdict="info",
        language=lang,
        summary=summary,
        reasons=reasons,
        recommendation=(
            f"Печатайте из {best.name}." if lang == "ru" else f"Print it in {best.name}."
        ),
        numbers={"max_service_c": best.max_service_c},
        confidence="medium" if purpose.strip() else "low",
    )


def _fastener_answer(
    text: str,
    holes: list[Hole],
    material: kb.MaterialKnowledge,
    lang: Language,
    region_hole: Hole | None,
) -> Answer:
    fastener = kb.fastener_for(text)
    lowered = text.lower()
    use: kb.FastenerUse = "clearance"
    if any(cue in lowered for cue in ("вплав", "insert", "heat", "втулк")):
        use = "heat_set"
    elif any(cue in lowered for cue in ("саморез", "нарез", "tap", "self", "thread into", "вкрут")):
        use = "tap"
    if fastener is None:
        summary = (
            "Укажите размер винта (например, M3 или M5), и я назову диаметр отверстия."
            if lang == "ru"
            else "Name the screw size (M3, M5, …) and I will give you the hole diameter."
        )
        return Answer(
            intent="fastener", verdict="info", language=lang, summary=summary, confidence="low"
        )
    diameter = kb.hole_for(fastener, use, material.id)
    use_word = {
        "clearance": ("под свободный проход" if lang == "ru" else "for the screw to pass through"),
        "tap": (
            "под вкручивание в пластик"
            if lang == "ru"
            else "for the screw to bite into the plastic"
        ),
        "heat_set": ("под вплавляемую втулку" if lang == "ru" else "for a heat-set insert"),
    }[use]
    summary = (
        f"Отверстие под {fastener.name} {use_word}: моделируйте {_mm(diameter)} "
        f"(с поправкой на усадку {material.name} {_mm(material.hole_undersize_mm)})."
        if lang == "ru"
        else f"A hole for {fastener.name} {use_word}: model {_mm(diameter)} "
        f"(includes {material.name}'s print undersize of {_mm(material.hole_undersize_mm)})."
    )
    numbers = {
        "diameter_mm": diameter,
        "clearance_mm": kb.hole_for(fastener, "clearance", material.id),
        "tap_mm": kb.hole_for(fastener, "tap", material.id),
        "heat_set_mm": kb.hole_for(fastener, "heat_set", material.id),
        "head_mm": fastener.head_mm,
    }
    reasons = [
        (
            f"Свободный проход {_mm(numbers['clearance_mm'])}, "
            f"под вкручивание {_mm(numbers['tap_mm'])}, "
            f"под втулку {_mm(numbers['heat_set_mm'])}; головка {_mm(fastener.head_mm)}."
            if lang == "ru"
            else f"Pass-through {_mm(numbers['clearance_mm'])}, "
            f"thread-forming {_mm(numbers['tap_mm'])}, "
            f"heat-set insert {_mm(numbers['heat_set_mm'])}; head {_mm(fastener.head_mm)}."
        )
    ]
    fix: Fix | None = None
    targets = [region_hole] if region_hole else holes
    off = [h for h in targets if abs(h.diameter_mm - diameter) > 0.05]
    if off:
        fix = Fix(
            label=(
                f"Отверстия под {fastener.name}" if lang == "ru" else f"Holes for {fastener.name}"
            ),
            operations=[
                {
                    "type": "set_parameter",
                    "operation": hole.operation_id,
                    "parameter": "diameter_mm",
                    "value": diameter,
                }
                for hole in off
            ],
        )
        reasons.append(
            f"В модели {len(off)} отверст. другого диаметра — исправление готово."
            if lang == "ru"
            else f"{len(off)} hole(s) in the model have another diameter — a fix is ready."
        )
    return Answer(
        intent="fastener",
        verdict="info",
        language=lang,
        summary=summary,
        reasons=reasons,
        recommendation=(f"Диаметр {_mm(diameter)}." if lang == "ru" else f"Use {_mm(diameter)}."),
        numbers=numbers,
        fix=fix,
        confidence="high",
    )


def _fit_answer(text: str, material: kb.MaterialKnowledge, lang: Language) -> Answer:
    fit = fit_of(text)
    allowance = kb.fit_allowance_mm(fit, material.id)
    fit_word = kb.FIT_WORDS_RU[fit] if lang == "ru" else fit.replace("_", " ") + " fit"
    sign = "+" if allowance >= 0 else "−"
    summary = (
        f"{fit_word.capitalize()} из {material.name}: {sign}{abs(allowance):g} мм к номиналу "
        f"(на сторону сопряжения)."
        if lang == "ru"
        else f"{fit_word.capitalize()} in {material.name}: {sign}{abs(allowance):g} mm "
        "on the nominal "
        f"(on the mating size)."
    )
    reasons = [
        (
            "FDM печатает отверстия меньше, а выступы больше номинала; допуск это компенсирует."
            if lang == "ru"
            else "FDM prints holes small and bosses big; the allowance compensates for that."
        ),
        (
            "Правило для сопла 0.4 мм; для точной посадки напечатайте пробник."
            if lang == "ru"
            else "A rule for a 0.4 mm nozzle; print a test coupon for a critical fit."
        ),
    ]
    return Answer(
        intent="fit",
        verdict="info",
        language=lang,
        summary=summary,
        reasons=reasons,
        recommendation=(
            f"Заложите {sign}{abs(allowance):g} мм."
            if lang == "ru"
            else f"Allow {sign}{abs(allowance):g} mm."
        ),
        numbers={"allowance_mm": allowance},
        confidence="medium",
    )


def _overview_answer(
    facts: Facts, material: kb.MaterialKnowledge, report_wall: float, lang: Language
) -> Answer:
    dims = " × ".join(f"{v:g}" for v in facts.bbox_mm) + " mm" if facts.bbox_mm else "?"
    mass = facts.mass_g.get(material.id)
    parts = [
        (f"Габариты {dims}" if lang == "ru" else f"Size {dims}"),
    ]
    if mass is not None:
        parts.append(
            f"масса из {material.name} {mass:g} г"
            if lang == "ru"
            else f"{mass:g} g in {material.name}"
        )
    if facts.walls is not None:
        parts.append(
            f"стенки от {_mm(facts.walls.min_mm)} (рекомендуемо {_mm(report_wall)})"
            if lang == "ru"
            else f"walls from {_mm(facts.walls.min_mm)} (recommended {_mm(report_wall)})"
        )
    return Answer(
        intent="overview",
        verdict="info",
        language=lang,
        summary="; ".join(parts) + ".",
        numbers={"recommended_wall_mm": report_wall},
        confidence="medium",
    )


# --- the report ----------------------------------------------------------------------------


def build_report(
    *,
    facts: Facts,
    operations: list[dict[str, Any]],
    material_id: str | None,
    question: str | None,
    purpose: str | None,
    region: dict[str, Any] | None,
    nozzle_mm: float = kb.DEFAULT_NOZZLE_MM,
) -> Report:
    """Everything the engineer has to say about this version, and the answer to the question."""
    text = " ".join(part for part in (question, purpose) if part)
    lang = language_of(text)
    material = kb.material(material_id)
    load = load_of(text)
    wall = kb.recommended_wall_mm(material.id, load, nozzle_mm)
    holes = holes_in(operations)

    words = kb.purpose_words(text)
    choices = [
        MaterialChoice(
            id=known.id,
            name=known.name,
            score=score,
            reasons=reasons,
            note=known.note_ru if lang == "ru" else known.note_en,
            max_service_c=known.max_service_c,
            mass_g=facts.mass_g.get(known.id),
        )
        for known, score, reasons in kb.rank_materials(words)
    ]

    recommendations: list[Answer] = []
    if facts.walls is not None and facts.walls.p5_mm < wall:
        recommendations.append(_walls_answer(facts, wall, material, lang, region=False))
    if facts.slenderness is not None and facts.slenderness > kb.SLENDER_RATIO:
        recommendations.append(_strength_answer(facts, wall, material, lang, load))
    for hole in holes:
        if not hole.fits and 2.0 <= hole.diameter_mm <= 10.0:
            nearest = min(
                kb.FASTENERS.values(),
                key=lambda f: abs(kb.hole_for(f, "clearance", material.id) - hole.diameter_mm),
            )
            target = kb.hole_for(nearest, "clearance", material.id)
            recommendations.append(
                Answer(
                    intent="fastener",
                    verdict="info",
                    language=lang,
                    summary=(
                        f"Отверстие {hole.operation_id} {_mm(hole.diameter_mm)} "
                        "не соответствует ни одному винту; "
                        f"под {nearest.name} нужно {_mm(target)}."
                        if lang == "ru"
                        else f"Hole {hole.operation_id} at {_mm(hole.diameter_mm)} "
                        "matches no screw; "
                        f"{nearest.name} would need {_mm(target)}."
                    ),
                    numbers={"diameter_mm": hole.diameter_mm, "suggested_mm": target},
                    fix=Fix(
                        label=f"{nearest.name} hole",
                        operations=[
                            {
                                "type": "set_parameter",
                                "operation": hole.operation_id,
                                "parameter": "diameter_mm",
                                "value": target,
                            }
                        ],
                    ),
                    confidence="low",
                )
            )

    answer: Answer | None = None
    if question:
        intent = intent_of(question)
        if intent == "walls":
            answer = _walls_answer(facts, wall, material, lang, region=region is not None)
        elif intent == "strength":
            answer = _strength_answer(facts, wall, material, lang, load)
        elif intent == "material":
            answer = _material_answer(choices, lang, text)
        elif intent == "fastener":
            answer = _fastener_answer(question, holes, material, lang, region_hole=None)
        elif intent == "fit":
            answer = _fit_answer(question, material, lang)
        else:
            answer = _overview_answer(facts, material, wall, lang)

    if answer is not None and answer.fix is not None:
        # The question already covers these operations; do not nag about them twice.
        covered = {op.get("operation") for op in answer.fix.operations}
        recommendations = [
            rec
            for rec in recommendations
            if rec.fix is None or not {op.get("operation") for op in rec.fix.operations} <= covered
        ]

    return Report(
        material_id=material.id,
        load=load,
        recommended_wall_mm=wall,
        facts=facts,
        holes=holes,
        materials=choices,
        recommendations=recommendations,
        answer=answer,
    )
