"""Deterministic rule-based planner (AI_PROVIDER=stub).

Covers the onboarding vocabulary — boxes, cylinders, organizers with
compartments, holes, fillets — in Russian and English, and asks for missing
dimensions instead of guessing. Used for tests, offline development and as
the fallback when no model provider is configured.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any

from app.ai.contract import PlannerOutput, PlannerResult, PlanRequest, Usage

PROVIDER = "stub"
MODEL = "rules-v1"

_DIMS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|in|inch|\"|m|м)?\s*[x×хX*]\s*"
    r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|in|inch|\"|m|м)?\s*[x×хX*]\s*"
    r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|in|inch|\"|m|м)?"
)
_TWO_DIMS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?\s*[x×хX*]\s*(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?"
)
_DIAMETER = re.compile(
    r"(?:ø|⌀|d\s*=?|diam\w*|диам\w*|под трубу|for (?:a )?pipe)"
    r"\s*(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?",
    re.IGNORECASE,
)
_HOLE = re.compile(
    r"(?:(\d+)\s*(?:x|×)?\s*)?(?:hole|holes|отверсти\w*|дыр\w*)\D{0,20}?(\d+(?:[.,]\d+)?)\s*(mm|мм)",
    re.IGNORECASE,
)
_COMPARTMENTS = re.compile(
    r"(\d+)\s*(?:compartments?|sections?|slots?|секци\w*|отделен\w*|ячее\w*|ячейк\w*)",
    re.IGNORECASE,
)
_FILLET = re.compile(
    r"(?:fillet|round\w*|скругл\w*)\D{0,20}?(\d+(?:[.,]\d+)?)\s*(mm|мм)", re.IGNORECASE
)
_HEIGHT = re.compile(
    r"(?:height|high|tall|высот\w*|высок\w*)\D{0,12}?(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?",
    re.IGNORECASE,
)

_UNIT_MM = {
    "mm": 1.0,
    "мм": 1.0,
    "cm": 10.0,
    "см": 10.0,
    "in": 25.4,
    "inch": 25.4,
    '"': 25.4,
    "m": 1000.0,
    "м": 1000.0,
    None: 1.0,
    "": 1.0,
}

_UNSUPPORTED = (
    "sphere",
    "шар",
    "сфер",
    "text",
    "текст",
    "надпись",
    "thread",
    "резьб",
    "gear",
    "шестер",
    "dragon",
    "figur",
    "фигурк",
    "statue",
    "статуэт",
    "organic",
)


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def _mm(value: str, unit: str | None) -> float:
    return round(_num(value) * _UNIT_MM.get((unit or "").lower(), 1.0), 4)


def _is_russian(text: str) -> bool:
    return bool(re.search(r"[а-яА-Я]", text))


def _stub_usage(prompt: str, output: str, started: float) -> Usage:
    return Usage(
        provider=PROVIDER,
        model=MODEL,
        input_tokens=max(len(prompt) // 4, 1),
        output_tokens=max(len(output) // 4, 1),
        cost_usd=Decimal("0"),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _clarify(
    request: PlanRequest, questions: list[str], goal: str, started: float
) -> PlannerResult:
    output = PlannerOutput(goal=goal, required_clarifications=questions)
    text = output.model_dump_json()
    return PlannerResult(
        output=output, raw_text=text, usage=_stub_usage(request.prompt, text, started)
    )


def _op(op_id: str, op_type: str, **params: Any) -> dict[str, Any]:
    return {"id": op_id, "type": op_type, "schema_version": 1, **params}


def plan(request: PlanRequest) -> PlannerResult:
    started = time.perf_counter()
    text = request.prompt.strip()
    lower = text.lower()
    ru = _is_russian(text)
    answers = " ".join(round_.get("answer", "") for round_ in request.conversation)
    combined = f"{text} {answers}"

    if any(word in lower for word in _UNSUPPORTED):
        question = (
            "Пока я умею строить только параметрические детали (коробки, цилиндры, выдавливание, "
            "отверстия, скругления). Опишите объект через эти формы или загрузите модель."
            if ru
            else "I can only build parametric parts so far (boxes, cylinders, extrusions, holes, "
            "fillets). Describe the object with those shapes or upload a model."
        )
        return _clarify(request, [question], text[:200], started)

    assumptions = ["Units are millimetres" if not ru else "Единицы — миллиметры"]
    operations: list[dict[str, Any]] = []
    validation: list[str] = []

    wants_cylinder = any(
        w in lower for w in ("cylinder", "цилиндр", "puck", "шайб", "диск", "disc")
    )
    dims = _DIMS.search(combined)
    diameter = _DIAMETER.search(combined)
    height = _HEIGHT.search(combined)

    if wants_cylinder:
        if not diameter or not height:
            question = (
                "Укажите диаметр и высоту цилиндра в мм (например, «диаметр 40 мм, высота 20 мм»)."
                if ru
                else "Please give the cylinder's diameter and height in mm "
                "(e.g. 'diameter 40 mm, height 20 mm')."
            )
            return _clarify(request, [question], text[:200], started)
        d = _mm(diameter.group(1), diameter.group(2))
        h = _mm(height.group(1), height.group(2))
        operations.append(_op("body", "create_cylinder", diameter_mm=d, height_mm=h))
        validation.append(f"cylinder diameter {d:g} mm, height {h:g} mm")
    else:
        if not dims:
            two = _TWO_DIMS.search(combined)
            question = (
                "Укажите размеры Ш×Г×В в мм (например, 200×100×50)."
                if ru
                else "Please give the size as W×D×H in mm (for example 200×100×50)."
            )
            if two:
                question = (
                    "Вижу два размера — какая высота (в мм)?"
                    if ru
                    else "I see two dimensions — what is the height (in mm)?"
                )
            return _clarify(request, [question], text[:200], started)
        w = _mm(dims.group(1), dims.group(2) or dims.group(6))
        d = _mm(dims.group(3), dims.group(4) or dims.group(6))
        h = _mm(dims.group(5), dims.group(6))
        operations.append(_op("body", "create_box", width_mm=w, depth_mm=d, height_mm=h))
        validation.append(f"bounding box is {w:g} x {d:g} x {h:g} mm")

        compartments = _COMPARTMENTS.search(combined)
        # A bare "box"/"коробка" is a solid block; containers must say so or give compartments.
        is_organizer = any(
            k in lower
            for k in (
                "organizer",
                "органайзер",
                "лоток",
                "tray",
                "ящик",
                "container",
                "контейнер",
                "hollow",
                "полый",
                "полая",
                "с секци",
                "with compartments",
            )
        )
        if compartments or is_organizer:
            wall, floor = 2.0, 3.0
            count = int(compartments.group(1)) if compartments else 1
            cols, rows = _grid(count, w, d)
            inner_w = (w - wall * (cols + 1)) / cols
            inner_d = (d - wall * (rows + 1)) / rows
            if inner_w <= 0 or inner_d <= 0 or h <= floor:
                question = (
                    "Секции не помещаются при стенке 2 мм — уменьшите число секций "
                    "или увеличьте размеры."
                    if ru
                    else "The compartments do not fit with 2 mm walls — reduce their number "
                    "or enlarge the box."
                )
                return _clarify(request, [question], text[:200], started)
            assumptions.append(
                f"{'Стенки' if ru else 'Walls'} {wall:g} mm, "
                f"{'дно' if ru else 'floor'} {floor:g} mm, "
                f"{cols}x{rows} {'сетка' if ru else 'grid'}"
            )
            index = 0
            for row in range(rows):
                for col in range(cols):
                    index += 1
                    x = wall + col * (inner_w + wall)
                    y = wall + row * (inner_d + wall)
                    operations.append(
                        _op(
                            f"pocket_{index}",
                            "create_box",
                            width_mm=round(inner_w, 4),
                            depth_mm=round(inner_d, 4),
                            height_mm=round(h - floor, 4),
                            origin_mm=[round(x, 4), round(y, 4), floor],
                        )
                    )
                    operations.append(
                        _op(
                            f"cut_{index}",
                            "boolean",
                            op="cut",
                            target="body",
                            tool=f"pocket_{index}",
                        )
                    )
            validation.append(f"{count} compartments, min wall {wall:g} mm")

    hole = _HOLE.search(combined)
    if hole:
        count = int(hole.group(1) or 1)
        hole_d = _mm(hole.group(2), hole.group(3))
        bbox_w = float(operations[0].get("width_mm") or operations[0]["diameter_mm"])
        bbox_d = float(operations[0].get("depth_mm") or operations[0]["diameter_mm"])
        for i in range(count):
            x = bbox_w * (i + 1) / (count + 1)
            operations.append(
                _op(
                    f"hole_{i + 1}",
                    "add_hole",
                    target="body",
                    face={"kind": "face_by_normal", "axis": "z", "sign": "+"},
                    position_mm=[round(x, 4), round(bbox_d / 2, 4)],
                    diameter_mm=hole_d,
                )
            )
        validation.append(f"{count} through hole(s) of {hole_d:g} mm")
        assumptions.append(
            "Holes are through and evenly spaced along X"
            if not ru
            else "Отверстия сквозные, равномерно по X"
        )

    fillet = _FILLET.search(combined)
    if fillet:
        operations.append(
            _op(
                "soften",
                "fillet",
                target="body",
                edges={"kind": "edges_parallel_to", "axis": "z"},
                radius_mm=_mm(fillet.group(1), fillet.group(2)),
            )
        )

    output = PlannerOutput(
        goal=text[:200],
        assumptions=assumptions,
        operations=operations,
        validation_steps=validation,
        expected_outputs=["body"],
    )
    raw = output.model_dump_json()
    return PlannerResult(
        output=output, raw_text=raw, usage=_stub_usage(request.prompt, raw, started)
    )


def _grid(count: int, width: float, depth: float) -> tuple[int, int]:
    """Columns x rows for `count` compartments, roughly matching the box aspect ratio."""
    best = (count, 1)
    best_score = float("inf")
    for cols in range(1, count + 1):
        if count % cols:
            continue
        rows = count // cols
        cell_w, cell_d = width / cols, depth / rows
        score = abs(cell_w - cell_d)
        if score < best_score:
            best, best_score = (cols, rows), score
    return best
