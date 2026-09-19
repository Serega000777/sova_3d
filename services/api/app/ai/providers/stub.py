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

from app.ai import smart_sizes
from app.ai.contract import PlannerOutput, PlannerResult, PlanRequest, Usage
from app.engineering import knowledge as kb

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
# The size can come before the word as easily as after it.
_HOLE_SIZE_FIRST = re.compile(
    r"(?:(\d+)\s*(?:x|×)\s*)?(\d+(?:[.,]\d+)?)\s*(mm|мм)\s*"
    r"(?:diameter\s*|диаметр\w*\s*)?(?:hole|holes|отверсти\w*|дыр\w*)",
    re.IGNORECASE,
)
_COMPARTMENTS = re.compile(
    r"(\d+)\s*(?:compartments?|sections?|slots?|секци\w*|отделен\w*|ячее\w*|ячейк\w*)",
    re.IGNORECASE,
)
_FILLET = re.compile(
    r"(?:fillet|round\w*|скругл\w*)\D{0,20}?(\d+(?:[.,]\d+)?)\s*(mm|мм)", re.IGNORECASE
)
_POCKET = re.compile(
    r"(pocket|recess|carve|cut ?out|cut|groove|карман|выемк\w*|углублен\w*|выреж\w*|"
    r"вырез\w*|паз)",
    re.IGNORECASE,
)
_BOSS = re.compile(
    r"(boss|pad|raise|emboss|bump|rib|прилив|бобышк\w*|выступ\w*|подним\w*|приподн\w*|"
    r"нараст\w*|ребр\w*)",
    re.IGNORECASE,
)
# "3 mm deep" and "depth 3 mm" are the same request; people write both.
_DEPTH = re.compile(
    r"(?:(?:depth|deep|глубин\w*|глубок\w*|высот\w*|толщин\w*)\D{0,12}?"
    r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)?"
    r"|(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)\s*(?:deep|tall|high|глубин\w*|высот\w*))",
    re.IGNORECASE,
)
_BARE_MM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см)\b", re.IGNORECASE)
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


def find_hole(text: str, undersize_mm: float | None = None) -> tuple[int, float] | None:
    """(count, diameter in mm) for either phrasing, or None if no hole was asked for.

    "Holes for M5" is a hole request too (F-025): the screw decides the diameter, with
    the print undersize already added — the printer's measured one when it has been
    calibrated (F-029), the material's typical one otherwise.
    """
    after = _HOLE.search(text)
    if after:
        return int(after.group(1) or 1), _mm(after.group(2), after.group(3))
    before = _HOLE_SIZE_FIRST.search(text)
    if before:
        return int(before.group(1) or 1), _mm(before.group(2), before.group(3))
    screw = smart_sizes.fastener_hole(text, smart_sizes.material_in(text), undersize_mm)
    if screw:
        return screw[0], screw[1]
    return None


def _undersize(request: PlanRequest) -> float | None:
    """The measured hole undersize a calibrated printer profile put into the context."""
    value = (request.printer_context or {}).get("hole_undersize_mm")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


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


def _unique(prefix: str, used: set[str]) -> str:
    candidate, n = prefix, 1
    while candidate in used:
        n += 1
        candidate = f"{prefix}_{n}"
    used.add(candidate)
    return candidate


def _edit_target(request: PlanRequest, base: list[dict[str, Any]]) -> str | None:
    """What the edit applies to: the viewport selection, else the last body built."""
    bodies = [
        op["id"] for op in base if op.get("type") in ("create_box", "create_cylinder", "extrude")
    ]
    for entity in request.selection_entity_ids:
        if entity in bodies:
            return entity
    return bodies[-1] if bodies else None


def _plan_region_edit(
    request: PlanRequest, text: str, combined: str, ru: bool, started: float
) -> PlannerResult:
    """F-062: the user circled part of the model and said what belongs there.

    The region is already millimetres, so the planner does not guess where: it puts the
    change at the outline's centre, sized to fit inside it. What it still has to decide is
    *what* — a hole, a pocket, a raised pad — and that comes from the words.
    """
    assert request.region is not None
    region = request.region
    box = region.bounds()
    centre = box.centre_mm
    size = box.size_mm
    base = [dict(op) for op in request.current_operations]
    target = region.target or _edit_target(request, base)
    if target is None or not base:
        return _clarify(
            request,
            [
                "Сначала нужна модель — опишите деталь, потом выделяйте на ней область."
                if ru
                else "There is no model yet: describe the part first, then outline an area on it."
            ],
            text[:200],
            started,
        )

    axis = region.surface_axis or "z"
    sign = region.surface_sign or "+"
    used = {str(op.get("id")) for op in base}
    operations = list(base)
    assumptions: list[str] = []
    validation: list[str] = []

    def depth_mm(default: float) -> float:
        found = _DEPTH.search(combined)
        if found:
            if found.group(1):
                return _mm(found.group(1), found.group(2))
            return _mm(found.group(3), found.group(4))
        # "выступ 2 мм" / "pocket 2 mm": with a pocket or a pad, a bare size is how deep.
        bare = _BARE_MM.search(combined)
        return _mm(bare.group(1), bare.group(2)) if bare else default

    hole = find_hole(combined)
    wants_pocket = bool(_POCKET.search(combined))
    wants_boss = bool(_BOSS.search(combined))
    # A stated diameter with no other verb still means a hole — that is what people say.
    diameter = _DIAMETER.search(combined)

    if hole or (diameter and not wants_pocket and not wants_boss):
        bore = hole[1] if hole else _mm(diameter.group(1), diameter.group(2))  # type: ignore[union-attr]
        plane = [a for a in ("x", "y", "z") if a != axis]
        position = [centre["xyz".index(plane[0])], centre["xyz".index(plane[1])]]
        operations.append(
            _op(
                _unique("region_hole", used),
                "add_hole",
                target=target,
                face={"kind": "face_by_normal", "axis": axis, "sign": sign},
                position_mm=[round(position[0], 4), round(position[1], 4)],
                diameter_mm=bore,
            )
        )
        validation.append(f"{bore:g} mm hole at the centre of the outlined area")
        assumptions.append(
            "Отверстие — в центре выделенной области"
            if ru
            else "The hole goes at the centre of the outlined area"
        )
    elif wants_pocket or wants_boss:
        # A block that fills the outline, inset a little, starting at the surface the user
        # drew on: into the body for a pocket, out of it for a raised pad.
        index = "xyz".index(axis)
        across = [i for i in range(3) if i != index]  # the two axes the outline spans
        surface = region.surface_mm
        if surface is None:
            surface = box.max_mm[index] if sign == "+" else box.min_mm[index]
        available = box.max_mm[index] - surface if sign == "+" else surface - box.min_mm[index]
        inward = (surface - box.min_mm[index]) if sign == "+" else (box.max_mm[index] - surface)
        margin = min(size[i] for i in across) * 0.1
        wanted = depth_mm(max(min(size[i] for i in across) / 4, 1.0))
        # Stay inside the outline: the region is what the user agreed to change.
        deep = max(min(wanted, inward if wants_pocket else available), 0.2)

        extents = [0.0, 0.0, 0.0]
        origin = [0.0, 0.0, 0.0]
        for i in across:
            extents[i] = max(size[i] - 2 * margin, 0.2)
            origin[i] = box.min_mm[i] + margin
        extents[index] = deep
        if (sign == "+") == wants_pocket:
            origin[index] = surface - deep  # cut down from a +face, build down from a -face
        else:
            origin[index] = surface

        tool = _unique("region_tool", used)
        operations.append(
            _op(
                tool,
                "create_box",
                width_mm=round(extents[0], 4),
                depth_mm=round(extents[1], 4),
                height_mm=round(extents[2], 4),
                origin_mm=[round(v, 4) for v in origin],
            )
        )
        width, depth = extents[across[0]], extents[across[1]]
        operations.append(
            _op(
                _unique("region_apply", used),
                "boolean",
                op="cut" if wants_pocket else "fuse",
                target=target,
                tool=tool,
            )
        )
        what = "pocket" if wants_pocket else "raised pad"
        validation.append(f"{what} {width:g} x {depth:g} x {deep:g} mm inside the outline")
        assumptions.append(
            f"{'Карман' if wants_pocket else 'Выступ'} вписан в выделенную область с отступом "
            f"{margin:g} мм"
            if ru
            else f"The {what} is inset {margin:g} mm from the outline"
        )
    else:
        return _clarify(
            request,
            [
                "Что сделать в выделенной области? Например: «отверстие 6 мм», "
                "«карман глубиной 3 мм», «выступ 2 мм»."
                if ru
                else "What should happen inside the outlined area? For example: 'a 6 mm hole', "
                "'a pocket 3 mm deep', 'a 2 mm raised pad'."
            ],
            text[:200],
            started,
        )

    output = PlannerOutput(
        goal=text[:200],
        assumptions=assumptions,
        operations=operations,
        validation_steps=validation,
        expected_outputs=[target],
    )
    raw = output.model_dump_json()
    return PlannerResult(
        output=output, raw_text=raw, usage=_stub_usage(request.prompt, raw, started)
    )


def _plan_edit(
    request: PlanRequest, text: str, combined: str, ru: bool, started: float
) -> PlannerResult:
    """Edit an existing model: replay its operations, then append the change (F-003).

    The plan is always the full history so the kernel stays stateless; only the
    appended operations are new, and they target the selected body (T-050/T-051).
    """
    base = [dict(op) for op in request.current_operations]
    target = _edit_target(request, base)
    if target is None:
        return _clarify(
            request,
            [
                "Не вижу параметрического тела для правки — опишите деталь заново."
                if ru
                else "This version has no parametric body to edit — describe the part instead."
            ],
            text[:200],
            started,
        )

    creator = next((op for op in base if op.get("id") == target), {})
    span_x = float(creator.get("width_mm") or creator.get("diameter_mm") or 0)
    span_y = float(creator.get("depth_mm") or creator.get("diameter_mm") or 0)

    used = {str(op.get("id")) for op in base}
    operations = list(base)
    assumptions: list[str] = []
    validation: list[str] = []

    # F-025: "so that an iPhone 17 Pro Max in its case fits here" resizes the cavity —
    # or cuts one — and grows the outside only if it has to.
    thing = smart_sizes.find_object(combined)
    if isinstance(thing, smart_sizes.Ambiguous):
        names = " / ".join(candidate.name for candidate in thing.candidates)
        return _clarify(
            request,
            [
                f"Какая модель: {names}? Или укажите размеры предмета Ш×Г×В в мм."
                if ru
                else f"Which model: {names}? Or give the object's size as W×D×H in mm."
            ],
            text[:200],
            started,
        )
    if thing is not None and creator.get("type") == "create_box":
        _edit_for_object(
            thing,
            smart_sizes.material_in(combined),
            base,
            creator,
            target,
            operations,
            used,
            assumptions,
            validation,
            ru,
        )

    dims = _DIMS.search(combined)
    if dims and thing is None:
        w = _mm(dims.group(1), dims.group(2) or dims.group(6))
        d = _mm(dims.group(3), dims.group(4) or dims.group(6))
        h = _mm(dims.group(5), dims.group(6))
        operations.append(
            _op(
                _unique("resize", used),
                "set_dimensions",
                target=target,
                width_mm=w,
                depth_mm=d,
                height_mm=h,
            )
        )
        validation.append(f"bounding box becomes {w:g} x {d:g} x {h:g} mm")
    else:
        height = _HEIGHT.search(combined)
        if height:
            h = _mm(height.group(1), height.group(2))
            operations.append(
                _op(_unique("resize", used), "set_dimensions", target=target, height_mm=h)
            )
            validation.append(f"height becomes {h:g} mm")

    found_hole = find_hole(combined, _undersize(request))
    if found_hole and span_x and span_y:
        count, hole_d = found_hole
        for i in range(count):
            operations.append(
                _op(
                    _unique(f"hole_{i + 1}", used),
                    "add_hole",
                    target=target,
                    face={"kind": "face_by_normal", "axis": "z", "sign": "+"},
                    position_mm=[round(span_x * (i + 1) / (count + 1), 4), round(span_y / 2, 4)],
                    diameter_mm=hole_d,
                )
            )
        validation.append(f"{count} through hole(s) of {hole_d:g} mm")
        assumptions.append(
            "Отверстия сквозные, равномерно по X"
            if ru
            else "Holes are through, evenly spaced along X"
        )

    fillet = _FILLET.search(combined)
    if fillet:
        radius = _mm(fillet.group(1), fillet.group(2))
        operations.append(
            _op(
                _unique("soften", used),
                "fillet",
                target=target,
                edges={"kind": "edges_parallel_to", "axis": "z"},
                radius_mm=radius,
            )
        )
        validation.append(f"vertical edges rounded to {radius:g} mm")

    # F-025: "добавь 0,3 мм допуска" / "подгони под трубу Ø32" change the one number that
    # decides the fit — every round opening in the plan — and nothing else.
    tolerance = smart_sizes.tolerance_mm(combined)
    pipe = smart_sizes.pipe_mm(combined) if not found_hole else None
    if tolerance is not None or pipe is not None:
        round_openings = [
            op
            for op in base
            if op.get("type") == "add_hole"
            or (op.get("type") == "create_cylinder" and _is_cut_tool(base, str(op.get("id"))))
        ]
        if not round_openings:
            return _clarify(
                request,
                [
                    "В модели нет отверстий или круглых вырезов, которые можно подогнать — "
                    "скажите, где нужен зазор."
                    if ru
                    else "The model has no holes or round cut-outs to adjust — "
                    "tell me where the clearance is needed."
                ],
                text[:200],
                started,
            )
        material_id = smart_sizes.material_in(combined)
        for op in round_openings:
            current = float(op["diameter_mm"])
            if pipe is not None:
                new_d = round(pipe + kb.fit_allowance_mm("sliding", material_id), 2)
            else:
                new_d = round(current + float(tolerance or 0), 2)
            operations.append(
                _op(
                    _unique("fit", used),
                    "set_parameter",
                    operation=str(op["id"]),
                    parameter="diameter_mm",
                    value=new_d,
                )
            )
            validation.append(f"{op['id']}: diameter {current:g} -> {new_d:g} mm")
        assumptions.append(
            (
                f"Подгонка под трубу Ø{pipe:g} мм со скользящей посадкой"
                if pipe is not None
                else f"Допуск {tolerance:g} мм добавлен к каждому отверстию"
            )
            if ru
            else (
                f"Sized for a Ø{pipe:g} mm pipe with a sliding fit"
                if pipe is not None
                else f"{tolerance:g} mm of clearance added to every hole"
            )
        )

    if len(operations) == len(base):
        return _clarify(
            request,
            [
                "Что изменить? Например: «скругли рёбра 2 мм», «отверстие 5 мм», "
                "«размер 80×20×25 мм»."
                if ru
                else "What should I change? For example: 'round the edges 2 mm', "
                "'a 5 mm hole', 'resize to 80×20×25 mm'."
            ],
            text[:200],
            started,
        )

    output = PlannerOutput(
        goal=text[:200],
        assumptions=assumptions,
        operations=operations,
        validation_steps=validation,
        expected_outputs=[target],
    )
    raw = output.model_dump_json()
    return PlannerResult(
        output=output, raw_text=raw, usage=_stub_usage(request.prompt, raw, started)
    )


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

    if request.region is not None:
        return _plan_region_edit(request, text, combined, ru, started)
    if request.current_operations:
        return _plan_edit(request, text, combined, ru, started)

    assumptions = ["Units are millimetres" if not ru else "Единицы — миллиметры"]
    operations: list[dict[str, Any]] = []
    validation: list[str] = []

    wants_cylinder = any(
        w in lower for w in ("cylinder", "цилиндр", "puck", "шайб", "диск", "disc")
    )
    dims = _DIMS.search(combined)
    diameter = _DIAMETER.search(combined)
    height = _HEIGHT.search(combined)

    # F-025: the thing the part is for decides its size — or asks which thing it is.
    material_id = smart_sizes.material_in(combined)
    thing = smart_sizes.find_object(combined)
    if isinstance(thing, smart_sizes.Ambiguous):
        names = " / ".join(candidate.name for candidate in thing.candidates)
        question = (
            f"Какая модель: {names}? Или укажите размеры предмета Ш×Г×В в мм."
            if ru
            else f"Which model: {names}? Or give the object's size as W×D×H in mm."
        )
        return _clarify(request, [question], text[:200], started)
    if thing is not None and not wants_cylinder:
        return _plan_for_object(request, thing, dims, material_id, text, ru, started)
    pipe = smart_sizes.pipe_mm(combined)
    if pipe and not dims and not wants_cylinder:
        return _plan_pipe_holder(request, pipe, material_id, text, ru, started)

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

    found_hole = find_hole(combined, _undersize(request))
    if found_hole:
        count, hole_d = found_hole
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


def _edit_for_object(
    thing: smart_sizes.ObjectMatch,
    material_id: str | None,
    base: list[dict[str, Any]],
    creator: dict[str, Any],
    target: str,
    operations: list[dict[str, Any]],
    used: set[str],
    assumptions: list[str],
    validation: list[str],
    ru: bool,
) -> None:
    """Fit the part's cavity to a known object, touching as few numbers as possible."""
    cw, cd, ch = thing.cavity_mm(material_id)
    if thing.holder:
        slot_w, slot_d, slot_h = cw, ch, SLOT_HEIGHT_MM
    else:
        slot_w, slot_d, slot_h = cw, cd, ch
    outer_w = float(creator.get("width_mm") or 0)
    outer_d = float(creator.get("depth_mm") or 0)
    outer_h = float(creator.get("height_mm") or 0)
    need_w = round(slot_w + 2 * WALL_MM, 2)
    need_d = round(slot_d + 2 * WALL_MM, 2)
    need_h = round(slot_h + FLOOR_MM, 2)

    # the outside grows only where the object does not fit
    grown = False
    for parameter, have, need in (
        ("width_mm", outer_w, need_w),
        ("depth_mm", outer_d, need_d),
        ("height_mm", outer_h, need_h),
    ):
        if have < need:
            operations.append(
                _op(
                    _unique("grow", used),
                    "set_parameter",
                    operation=target,
                    parameter=parameter,
                    value=need,
                )
            )
            grown = True
    outer_w, outer_d, outer_h = max(outer_w, need_w), max(outer_d, need_d), max(outer_h, need_h)

    cavity = next(
        (
            op
            for op in base
            if op.get("type") == "create_box" and _is_cut_tool(base, str(op.get("id")))
        ),
        None,
    )
    if cavity is not None:
        # resize the cavity that is there; its origin stays where it was
        for parameter, value in (
            ("width_mm", round(slot_w, 4)),
            ("depth_mm", round(slot_d, 4)),
            ("height_mm", round(outer_h - FLOOR_MM + 1, 4)),
        ):
            if float(cavity.get(parameter) or 0) != value:
                operations.append(
                    _op(
                        _unique("fit", used),
                        "set_parameter",
                        operation=str(cavity["id"]),
                        parameter=parameter,
                        value=value,
                    )
                )
    else:
        cavity_id = _unique("cavity", used)
        operations.append(
            _op(
                cavity_id,
                "create_box",
                width_mm=round(slot_w, 4),
                depth_mm=round(slot_d, 4),
                height_mm=round(outer_h - FLOOR_MM + 1, 4),
                origin_mm=[
                    round((outer_w - slot_w) / 2, 4),
                    round((outer_d - slot_d) / 2, 4),
                    FLOOR_MM,
                ],
            )
        )
        operations.append(
            _op(_unique("cut_cavity", used), "boolean", op="cut", target=target, tool=cavity_id)
        )
    gap = kb.fit_allowance_mm("sliding", material_id)
    assumptions.append(
        (
            f"{thing.object.name}: {thing.object.width_mm:g} × {thing.object.depth_mm:g} × "
            f"{thing.object.height_mm:g} мм из каталога, скользящая посадка +{gap:g} мм"
            + (" , с чехлом" if thing.in_case else "")
        )
        if ru
        else (
            f"{thing.object.name}: {thing.object.width_mm:g} × {thing.object.depth_mm:g} × "
            f"{thing.object.height_mm:g} mm from the catalogue, sliding fit +{gap:g} mm"
            + (", with its case" if thing.in_case else "")
        )
    )
    if grown:
        assumptions.append(
            f"Корпус увеличен до {outer_w:g} × {outer_d:g} × {outer_h:g} мм, "
            "чтобы предмет поместился"
            if ru
            else f"The body grew to {outer_w:g} × {outer_d:g} × {outer_h:g} mm so the object fits"
        )
    validation.append(f"cavity {slot_w:g} x {slot_d:g} mm takes {thing.object.name}")


def _is_cut_tool(base: list[dict[str, Any]], op_id: str) -> bool:
    """A cylinder consumed by a boolean cut is an opening, not a body."""
    return any(
        op.get("type") == "boolean" and op.get("op") == "cut" and op.get("tool") == op_id
        for op in base
    )


WALL_MM = 2.0
FLOOR_MM = 3.0
SLOT_HEIGHT_MM = 30.0


def _finish(
    request: PlanRequest,
    text: str,
    operations: list[dict[str, Any]],
    assumptions: list[str],
    validation: list[str],
    started: float,
) -> PlannerResult:
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


def _plan_for_object(
    request: PlanRequest,
    thing: smart_sizes.ObjectMatch,
    dims: re.Match[str] | None,
    material_id: str | None,
    text: str,
    ru: bool,
    started: float,
) -> PlannerResult:
    """A part that holds a known object (T-121): the cavity is the object plus a fit.

    A holder stands the object up in a slot; anything else lays it flat in a pocket. When
    the user also gave an outer size, that is kept and the cavity is centred in it.
    """
    cw, cd, ch = thing.cavity_mm(material_id)
    if thing.holder:
        # standing: the slot is as wide as the object and as deep as it is thick
        slot_w, slot_d, slot_h = cw, ch, SLOT_HEIGHT_MM
    else:
        slot_w, slot_d, slot_h = cw, cd, ch
    if dims:
        w = _mm(dims.group(1), dims.group(2) or dims.group(6))
        d = _mm(dims.group(3), dims.group(4) or dims.group(6))
        h = _mm(dims.group(5), dims.group(6))
        if w < slot_w + 2 * WALL_MM or d < slot_d + 2 * WALL_MM or h <= FLOOR_MM:
            need = f"{slot_w + 2 * WALL_MM:g} × {slot_d + 2 * WALL_MM:g} мм"
            return _clarify(
                request,
                [
                    f"{thing.object.name} не поместится: нужно хотя бы {need} снаружи "
                    f"при стенке {WALL_MM:g} мм. Увеличить размеры?"
                    if ru
                    else f"{thing.object.name} will not fit: the outside needs at least "
                    f"{need.replace('мм', 'mm')} with {WALL_MM:g} mm walls. Enlarge it?"
                ],
                text[:200],
                started,
            )
        slot_h = min(slot_h, h - FLOOR_MM)
    else:
        w = round(slot_w + 2 * WALL_MM, 2)
        d = round(slot_d + 2 * WALL_MM, 2)
        h = round(slot_h + FLOOR_MM, 2)
    x = round((w - slot_w) / 2, 4)
    y = round((d - slot_d) / 2, 4)
    operations = [
        _op("body", "create_box", width_mm=w, depth_mm=d, height_mm=h),
        _op(
            "cavity",
            "create_box",
            width_mm=round(slot_w, 4),
            depth_mm=round(slot_d, 4),
            height_mm=round(h - FLOOR_MM + 1, 4),  # opens through the top
            origin_mm=[x, y, FLOOR_MM],
        ),
        _op("cut_cavity", "boolean", op="cut", target="body", tool="cavity"),
    ]
    gap = kb.fit_allowance_mm("sliding", material_id)
    what = thing.object.name + (" в чехле" if thing.in_case and ru else "")
    what = thing.object.name + (
        " in its case" if thing.in_case and not ru else what[len(thing.object.name) :]
    )
    assumptions = [
        (
            f"Единицы — миллиметры; {thing.object.name}: {thing.object.width_mm:g} × "
            f"{thing.object.depth_mm:g} × {thing.object.height_mm:g} мм из каталога"
            if ru
            else f"Units are millimetres; {thing.object.name}: {thing.object.width_mm:g} × "
            f"{thing.object.depth_mm:g} × {thing.object.height_mm:g} mm from the catalogue"
        ),
        (
            f"Скользящая посадка +{gap:g} мм, стенки {WALL_MM:g} мм, дно {FLOOR_MM:g} мм"
            if ru
            else f"Sliding fit +{gap:g} mm, walls {WALL_MM:g} mm, floor {FLOOR_MM:g} mm"
        ),
    ]
    if thing.in_case:
        assumptions.append(
            f"Чехол: +{thing.object.case_side_mm:g} мм по сторонам, "
            f"+{thing.object.case_thickness_mm:g} мм по толщине"
            if ru
            else f"Case: +{thing.object.case_side_mm:g} mm per side, "
            f"+{thing.object.case_thickness_mm:g} mm of thickness"
        )
    validation = [
        f"bounding box is {w:g} x {d:g} x {h:g} mm",
        f"cavity {slot_w:g} x {slot_d:g} mm takes {what}",
    ]
    return _finish(request, text, operations, assumptions, validation, started)


PIPE_WALL_MM = 6.0
PIPE_LENGTH_MM = 30.0


def _plan_pipe_holder(
    request: PlanRequest,
    pipe: float,
    material_id: str | None,
    text: str,
    ru: bool,
    started: float,
) -> PlannerResult:
    """A block with a round opening for a pipe or rod (T-121): the bore is the pipe + fit."""
    bore = round(pipe + kb.fit_allowance_mm("sliding", material_id), 2)
    side = round(bore + 2 * PIPE_WALL_MM, 2)
    operations = [
        _op("body", "create_box", width_mm=side, depth_mm=PIPE_LENGTH_MM, height_mm=side),
        _op(
            "bore",
            "create_cylinder",
            diameter_mm=bore,
            height_mm=PIPE_LENGTH_MM + 2,
            axis="y",
            origin_mm=[round(side / 2, 4), -1.0, round(side / 2, 4)],
        ),
        _op("cut_bore", "boolean", op="cut", target="body", tool="bore"),
    ]
    assumptions = [
        (
            f"Труба Ø{pipe:g} мм проходит насквозь по Y; отверстие Ø{bore:g} мм "
            f"(скользящая посадка), стенка {PIPE_WALL_MM:g} мм, длина {PIPE_LENGTH_MM:g} мм"
            if ru
            else f"The Ø{pipe:g} mm pipe passes through along Y; bore Ø{bore:g} mm "
            f"(sliding fit), wall {PIPE_WALL_MM:g} mm, length {PIPE_LENGTH_MM:g} mm"
        )
    ]
    validation = [
        f"bounding box is {side:g} x {PIPE_LENGTH_MM:g} x {side:g} mm",
        f"bore {bore:g} mm",
    ]
    return _finish(request, text, operations, assumptions, validation, started)


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
