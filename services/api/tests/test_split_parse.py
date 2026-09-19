"""T-142 (F-081): the cutting a sentence asks for."""

from __future__ import annotations

import pytest

from app.services.splitting import SplitIntent, parse


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("разрежь на 3 части", SplitIntent(parts=3)),
        ("Раздели статуэтку на четыре части по высоте", SplitIntent(parts=4, axis="z")),
        ("распили пополам без штифтов", SplitIntent(parts=2, dowels=False)),
        ("разрежь так, чтобы влезло в принтер", SplitIntent(fit_bed=True)),
        ("порежь на части под мой принтер", SplitIntent(fit_bed=True)),
        ("cut it in half", SplitIntent(parts=2)),
        ("split the figure into three pieces lengthwise", SplitIntent(parts=3, axis="x")),
        ("split it so it fits my printer, no dowels", SplitIntent(fit_bed=True, dowels=False)),
        ("divide into 2 parts along y", SplitIntent(parts=2, axis="y")),
    ],
)
def test_cutting_sentences(prompt: str, expected: SplitIntent) -> None:
    assert parse(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "cut a slot 5 mm deep here",  # an edit for the planner
        "вырежи паз 3 мм",
        "Organizer 120x80x40 mm with 4 compartments",
        "make it wider by 20 mm",
        "split the difference",
    ],
)
def test_other_sentences_are_not_cuts(prompt: str) -> None:
    assert parse(prompt) is None


def test_the_intent_becomes_a_worker_request() -> None:
    assert SplitIntent(parts=3, axis="z").request(None) == {
        "connectors": {"kind": "dowel"},
        "parts": 3,
        "axis": "z",
    }
    bed = {"x_mm": 220.0, "y_mm": 220.0, "z_mm": 250.0}
    assert SplitIntent(fit_bed=True, dowels=False).request(bed) == {
        "connectors": {"kind": "none"},
        "bed": bed,
    }
