"""T-124 (F-070): every template is a sentence the planner is known to build."""

from __future__ import annotations

import pytest

from app.ai.contract import PlanRequest
from app.ai.planner import StubPlanner, plan_with_repair
from app.api.errors import ValidationFailedError
from app.services import templates


@pytest.mark.parametrize("template", templates.TEMPLATES, ids=lambda t: t.id)
@pytest.mark.parametrize("language", ["en", "ru"])
def test_every_template_builds_with_its_defaults(
    template: templates.Template, language: str
) -> None:
    prompt = templates.render_prompt(template, {}, language)
    outcome = plan_with_repair(StubPlanner(), PlanRequest(prompt=prompt))
    assert outcome.status == "planned", (template.id, language, prompt, outcome)
    assert outcome.plan is not None and outcome.plan.operations


def test_parameters_are_checked_against_their_ranges() -> None:
    organizer = templates.get_template("organizer")
    prompt = templates.render_prompt(organizer, {"w": 120, "d": 80, "h": 30, "n": 4}, "ru")
    assert prompt == "Органайзер 120×80×30 мм с 4 секциями, скругление 1.5 мм"
    with pytest.raises(ValidationFailedError):
        templates.render_prompt(organizer, {"n": 40}, "en")
    with pytest.raises(ValidationFailedError):
        templates.render_prompt(organizer, {"w": "wide"}, "en")


def test_templates_come_with_something_to_try_next() -> None:
    for template in templates.TEMPLATES:
        assert template.next_steps_en and template.next_steps_ru
        assert template.description_en and template.description_ru


def test_an_unknown_template_is_a_404() -> None:
    from app.api.errors import NotFoundError

    with pytest.raises(NotFoundError):
        templates.get_template("castle")
