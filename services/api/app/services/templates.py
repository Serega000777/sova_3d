"""Templates and quick starts (T-124/T-125, F-070): a first project that is not a blank page.

Each template is a sentence the planner is known to build — with a few numbers the user
can change before it is built — plus the two or three things worth trying next on the
result. The catalogue is data: adding a template is adding an entry, not code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.config import Settings
from app.models.core import Project
from app.models.execution import AIRequest, Job
from app.services import ai_commands, projects


@dataclass(frozen=True)
class Parameter:
    id: str
    label_en: str
    label_ru: str
    default: float
    min: float
    max: float
    unit: str = "mm"


@dataclass(frozen=True)
class Template:
    id: str
    category: str
    title_en: str
    title_ru: str
    description_en: str
    description_ru: str
    # {w} {d} {h} ... are filled from the parameters; the sentence is what the planner gets
    prompt_en: str
    prompt_ru: str
    parameters: tuple[Parameter, ...]
    next_steps_en: tuple[str, ...] = field(default_factory=tuple)
    next_steps_ru: tuple[str, ...] = field(default_factory=tuple)


def _p(id_: str, en: str, ru: str, default: float, lo: float, hi: float) -> Parameter:
    return Parameter(id_, en, ru, default, lo, hi)


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="organizer",
        category="home",
        title_en="Desk organizer",
        title_ru="Органайзер для стола",
        description_en="A tray with compartments, 2 mm walls, rounded corners.",
        description_ru="Лоток с секциями, стенки 2 мм, скруглённые углы.",
        prompt_en="Organizer {w}x{d}x{h} mm with {n} compartments, fillet 1.5 mm",
        prompt_ru="Органайзер {w}×{d}×{h} мм с {n} секциями, скругление 1.5 мм",
        parameters=(
            _p("w", "Width", "Ширина", 200, 40, 300),
            _p("d", "Depth", "Глубина", 100, 40, 300),
            _p("h", "Height", "Высота", 50, 10, 120),
            Parameter("n", "Compartments", "Секции", 6, 1, 12, unit=""),
        ),
        next_steps_en=(
            "Outline one compartment and say 'make it 30 mm deep'",
            "Ask the engineer: 'is this wall too thin?'",
            "Paint the dividers a different colour",
        ),
        next_steps_ru=(
            "Обведите одну секцию и скажите «сделай её глубиной 30 мм»",
            "Спросите инженера: «Эта стенка слишком тонкая?»",
            "Покрасьте перегородки в другой цвет",
        ),
    ),
    Template(
        id="phone-stand",
        category="desk",
        title_en="Phone stand",
        title_ru="Подставка для телефона",
        description_en="A slot sized for your phone from the catalogue — case included.",
        description_ru="Слот под ваш телефон из каталога — с учётом чехла.",
        prompt_en="A stand so that an iPhone 17 Pro Max in its case fits here",
        prompt_ru="Подставка, чтобы сюда помещался iPhone 17 Pro Max в чехле",
        parameters=(),
        next_steps_en=(
            "Type another phone: 'make it fit a Galaxy S25'",
            "Add a cable slot: outline the front and say 'a 12 mm hole here'",
        ),
        next_steps_ru=(
            "Назовите другой телефон: «сделай под Galaxy S25»",
            "Добавьте вырез под кабель: обведите переднюю стенку и скажите «отверстие 12 мм здесь»",
        ),
    ),
    Template(
        id="pipe-holder",
        category="workshop",
        title_en="Pipe holder",
        title_ru="Держатель для трубы",
        description_en="A block with a bore for a pipe or rod, sliding fit.",
        description_ru="Блок с отверстием под трубу или стержень, скользящая посадка.",
        prompt_en="Holder for a Ø{pipe} mm pipe",
        prompt_ru="Держатель под трубу Ø{pipe} мм",
        parameters=(_p("pipe", "Pipe diameter", "Диаметр трубы", 32, 6, 120),),
        next_steps_en=(
            "Add mounting holes: 'two holes for M5'",
            "Ask the engineer which material survives outdoors",
        ),
        next_steps_ru=(
            "Добавьте крепёж: «два отверстия под М5»",
            "Спросите инженера, какой пластик выдержит улицу",
        ),
    ),
    Template(
        id="mounting-plate",
        category="workshop",
        title_en="Mounting plate",
        title_ru="Монтажная пластина",
        description_en="A plate with screw holes for the size you name.",
        description_ru="Пластина с отверстиями под винты нужного размера.",
        prompt_en="Plate {w}x{d}x{h} mm with {n} holes for M{m}",
        prompt_ru="Пластина {w}×{d}×{h} мм, {n} отверстия под М{m}",
        parameters=(
            _p("w", "Width", "Ширина", 80, 20, 300),
            _p("d", "Depth", "Глубина", 40, 20, 300),
            _p("h", "Thickness", "Толщина", 4, 2, 20),
            Parameter("n", "Holes", "Отверстия", 2, 1, 6, unit=""),
            Parameter("m", "Screw M", "Винт M", 4, 2, 8, unit=""),
        ),
        next_steps_en=(
            "Ask the engineer: 'will it hold 5 kg?'",
            "Say 'add 0.3 mm of clearance' if the screws bind",
        ),
        next_steps_ru=(
            "Спросите инженера: «выдержит 5 кг?»",
            "Скажите «добавь 0,3 мм допуска», если винты идут туго",
        ),
    ),
    Template(
        id="battery-tray",
        category="home",
        title_en="AA battery tray",
        title_ru="Лоток для батареек AA",
        description_en="A pocket that takes an AA cell with a sliding fit.",
        description_ru="Гнездо под батарейку AA со скользящей посадкой.",
        prompt_en="A tray for an AA battery",
        prompt_ru="Лоток под батарейку AA",
        parameters=(),
        next_steps_en=("Paint it", "Check printability before you export"),
        next_steps_ru=("Покрасьте его", "Проверьте печатаемость перед экспортом"),
    ),
    Template(
        id="puck",
        category="learn",
        title_en="A simple cylinder",
        title_ru="Простой цилиндр",
        description_en="The smallest possible start: a puck you can resize and drill.",
        description_ru="Самое простое начало: шайба, которую можно изменить и просверлить.",
        prompt_en="Cylinder diameter {dia} mm, height {h} mm",
        prompt_ru="Цилиндр диаметр {dia} мм, высота {h} мм",
        parameters=(
            _p("dia", "Diameter", "Диаметр", 40, 5, 200),
            _p("h", "Height", "Высота", 20, 1, 200),
        ),
        next_steps_en=(
            "Change a number in the inspector",
            "Say 'a 6 mm hole' and watch the version history grow",
            "Type 'undo' to go back",
        ),
        next_steps_ru=(
            "Измените число в инспекторе",
            "Скажите «отверстие 6 мм» и посмотрите, как растёт история версий",
            "Напишите «отмени», чтобы вернуться",
        ),
    ),
)

BY_ID = {template.id: template for template in TEMPLATES}


def list_templates() -> list[Template]:
    return list(TEMPLATES)


def get_template(template_id: str) -> Template:
    template = BY_ID.get(template_id)
    if template is None:
        raise NotFoundError("template", template_id)
    return template


def render_prompt(template: Template, params: dict[str, Any], language: str) -> str:
    """The sentence the planner gets, with every number checked against its range."""
    values: dict[str, Any] = {}
    for parameter in template.parameters:
        raw = params.get(parameter.id, parameter.default)
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationFailedError(
                f"parameter {parameter.id!r} must be a number", {"value": raw}
            ) from exc
        if not parameter.min <= value <= parameter.max:
            raise ValidationFailedError(
                f"parameter {parameter.id!r} must be between {parameter.min:g} "
                f"and {parameter.max:g}",
                {"value": value},
            )
        values[parameter.id] = int(value) if value == int(value) else value
    pattern = template.prompt_ru if language == "ru" else template.prompt_en
    return pattern.format(**values)


def start_from_template(
    db: Session,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    template_id: str,
    params: dict[str, Any],
    language: str = "en",
    name: str | None = None,
) -> tuple[Project, AIRequest, Job]:
    """A new project whose first version is being built from the template's sentence."""
    template = get_template(template_id)
    prompt = render_prompt(template, params, language)
    title = template.title_ru if language == "ru" else template.title_en
    project = projects.create_project(
        db, user_id=user_id, workspace_id=workspace_id, name=name or title
    )
    request, job = ai_commands.create_command(
        db,
        settings,
        user_id=user_id,
        project_id=project.id,
        prompt=prompt,
        client_capabilities={"template_id": template.id},
    )
    return project, request, job
