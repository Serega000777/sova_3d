"""Item 41: a strict, deterministic RU/EN description of one rectangular house.

The parser is deliberately small. It never guesses: every dimension must carry an explicit
unit, every required field must be present exactly once (or repeated with the same value),
and any clause it does not understand rejects the whole command. The result is a canonical
``HouseBoxRequest`` in whole millimetres that a person can verify before any job exists.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Language = Literal["ru", "en"]
Field = Literal["length_mm", "width_mm", "floor_height_mm", "floors", "shape"]

REQUIRED: tuple[Field, ...] = ("length_mm", "width_mm", "floor_height_mm", "floors")
BOUNDS: dict[Field, tuple[int, int]] = {
    "length_mm": (2_000, 50_000),
    "width_mm": (2_000, 50_000),
    "floor_height_mm": (2_200, 6_000),
    "floors": (1, 3),
}
EXAMPLES = (
    "Создай двухэтажный прямоугольный дом 12 × 8 м, высота этажа 3 м",
    "Build a rectangular house 12 m x 8 m, 2 floors, floor height 3000 mm",
)


class HouseTextError(ValueError):
    """A fail-closed refusal with a machine reason and user-safe details."""

    def __init__(self, reason: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.details = {"reason": reason, **(details or {}), "examples": list(EXAMPLES)}


@dataclass(frozen=True)
class ParsedHouseText:
    language: Language
    length_mm: int
    width_mm: int
    floor_height_mm: int
    floors: int
    shape: Literal["rectangle"]
    sources: dict[str, str] = field(default_factory=dict)

    def request(self) -> dict[str, Any]:
        return {
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "floor_height_mm": self.floor_height_mm,
            "floors": self.floors,
            "shape": self.shape,
        }


_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = (
    r"(?:мм|миллиметр(?:а|ов)?|см|сантиметр(?:а|ов)?|м|метр(?:а|ов)?"
    r"|mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|m|met(?:er|re)s?)(?![a-zа-я])"
)
_FACTORS = {"мм": 1, "см": 10, "м": 1_000}


def _q(name: str) -> str:
    """A number followed by an optional unit, captured as ``name`` / ``name_u``."""
    return rf"(?P<{name}>{_NUM})\s*(?P<{name}_u>{_UNIT})?"


_RU_VERBS = r"(?:создай|построй|сделай|спроектируй|нужен)"
_EN_VERBS = r"(?:create|build|make|design)"
_HEADS: dict[Language, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:{_RU_VERBS}\s+)?(?P<mods>(?:[^\s,;:]+\s+)*?)дом(?P<rest>(?=[\s,;:]|$).*)$"
    ),
    "en": re.compile(
        rf"^(?:{_EN_VERBS}\s+)?(?:an?\s+)?(?P<mods>(?:[^\s,;:]+\s+)*?)house(?P<rest>(?=[\s,;:]|$).*)$"
    ),
}
_WORD_FLOORS = {
    "один": 1, "одном": 1, "два": 2, "двух": 2, "три": 3, "трех": 3,
    "one": 1, "two": 2, "three": 3,
}  # fmt: skip
_FLOOR_MODIFIERS: dict[Language, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:(?P<word>одно|двух|трех)этажный|(?P<n>\d+)-?(?:х-?)?этажный)$"),
    "en": re.compile(r"^(?:(?P<word>single|one|two|three)|(?P<n>\d+))-?stor(?:e?y|ied)$"),
}
_MOD_WORD = {"одно": 1, "двух": 2, "трех": 3, "single": 1, "one": 1, "two": 2, "three": 3}
_RECTANGULAR: dict[Language, re.Pattern[str]] = {
    "ru": re.compile(r"^прямоугольн(?:ый|ой формы|ая форма|ой)$"),
    "en": re.compile(r"^rectangular(?: shape)?$"),
}
_OTHER_SHAPE = re.compile(
    r"(?:г-?образн|т-?образн|п-?образн|углов|кругл|овальн|l-?shaped|t-?shaped|u-?shaped"
    r"|round|circular|oval)"
)
_UNSUPPORTED = re.compile(
    r"(?:лестниц|крыш|кровл|окн|двер|комнат|спальн|кухн|гараж|подвал|мансард|балкон|террас"
    r"|stair|roof|window|door|room|bedroom|kitchen|garage|basement|attic|balcony|terrace)"
)
_AMBIGUOUS_HEIGHT = re.compile(r"(?:высот|потол|height|ceiling|tall)")

_CLAUSES: dict[Language, list[tuple[str, str]]] = {
    "ru": [
        (
            "footprint",
            rf"^(?:(?:размер(?:ом)?|размеры|габарит(?:ы|ами)?)\s+)?{_q('a')}\s*(?:x|х|\*|на)\s*"
            rf"{_q('b')}(?:\s+в\s+плане)?$",
        ),
        ("length_mm", rf"^(?:длин(?:а|ой|у)\s+{_q('v')}|{_q('w')}\s+(?:в\s+)?длину)$"),
        ("width_mm", rf"^(?:ширин(?:а|ой|у)\s+{_q('v')}|{_q('w')}\s+(?:в\s+)?ширину)$"),
        (
            "floor_height_mm",
            rf"^(?:высот(?:а|ой|у)\s+этажа|этаж(?:и|ами)?\s+(?:высотой|по))\s+{_q('v')}$",
        ),
        (
            "floors",
            r"^(?:в\s+)?(?P<n>\d+|один|одном|два|двух|три|трех)\s+этаж(?:а|ей|ах)?$"
            r"|^этажност(?:ь|ью)\s+(?P<m>\d+)$",
        ),
        ("shape", r"^прямоугольн(?:ый|ой формы|ая форма|ой)$"),
    ],
    "en": [
        (
            "footprint",
            rf"^(?:(?:size|footprint|dimensions)\s+(?:of\s+)?)?{_q('a')}\s*(?:x|\*|by)\s*"
            rf"{_q('b')}(?:\s+footprint)?$",
        ),
        ("length_mm", rf"^(?:(?:a\s+)?length\s+(?:of\s+)?{_q('v')}|{_q('w')}\s+long)$"),
        ("width_mm", rf"^(?:(?:a\s+)?width\s+(?:of\s+)?{_q('v')}|{_q('w')}\s+wide)$"),
        (
            "floor_height_mm",
            rf"^(?:(?:a\s+)?(?:floor|storey|story)\s+height\s+(?:of\s+)?{_q('v')}"
            rf"|{_q('w')}\s+per\s+(?:floor|storey|story))$",
        ),
        (
            "floors",
            r"^(?P<n>\d+|one|two|three)\s+(?:floors?|storeys?|stor(?:y|ies)|levels?)$",
        ),
        ("shape", r"^rectangular(?:\s+shape)?$"),
    ],
}
_COMPILED = {
    language: [(name, re.compile(pattern)) for name, pattern in clauses]
    for language, clauses in _CLAUSES.items()
}
_SPLIT = re.compile(r"\s*(?:;|,(?!\d)|\s+и\s+|\s+and\s+|\s+with\s+|\s+с\s+)\s*")
_CONNECTIVE = re.compile(r"^(?:с|со|и|with|and|:|—|-)\s*")


def _normalise(prompt: str) -> str:
    text = prompt.lower().replace("ё", "е").replace("×", " x ").replace("–", "-")
    text = " ".join(text.split())
    return re.sub(r"[.!]$", "", text).strip()


def _millimetres(number: str, unit: str | None, field_name: str, fragment: str) -> int:
    if unit is None:
        raise HouseTextError(
            "missing_unit",
            f"every dimension needs an explicit unit (mm, cm or m): '{fragment}'",
            {"field": field_name, "fragment": fragment},
        )
    if unit.startswith(("мм", "mm", "миллиметр", "millimet")):
        key = "мм"
    elif unit.startswith(("см", "cm", "сантиметр", "centimet")):
        key = "см"
    else:
        key = "м"
    value = Decimal(number.replace(",", ".")) * _FACTORS[key]
    if value != value.to_integral_value():
        raise HouseTextError(
            "sub_millimetre",
            f"'{fragment}' does not resolve to whole millimetres",
            {"field": field_name, "fragment": fragment},
        )
    return int(value)


def _floor_count(token: str) -> int:
    return _WORD_FLOORS[token] if token in _WORD_FLOORS else int(token)


class _Collector:
    def __init__(self) -> None:
        self.values: dict[str, int | str] = {}
        self.sources: dict[str, str] = {}

    def put(self, name: str, value: int | str, fragment: str) -> None:
        if name in self.values and self.values[name] != value:
            raise HouseTextError(
                "conflict",
                f"conflicting values for {name}: '{self.sources[name]}' and '{fragment}'",
                {"field": name, "fragments": [self.sources[name], fragment]},
            )
        self.values.setdefault(name, value)
        self.sources.setdefault(name, fragment)


def _modifier(language: Language, token: str, out: _Collector) -> None:
    floors = _FLOOR_MODIFIERS[language].fullmatch(token)
    if floors is not None:
        word = floors.group("word")
        out.put("floors", _MOD_WORD[word] if word else int(floors.group("n")), token)
        return
    if _RECTANGULAR[language].fullmatch(token):
        out.put("shape", "rectangle", token)
        return
    _refuse_unknown(token)


def _refuse_unknown(fragment: str) -> None:
    if _OTHER_SHAPE.search(fragment):
        raise HouseTextError(
            "unsupported_shape",
            "only a rectangular house can be described in text for now",
            {"fragment": fragment},
        )
    if _UNSUPPORTED.search(fragment):
        raise HouseTextError(
            "unsupported_feature",
            f"'{fragment}' is not supported by the bounded text-to-house command",
            {"fragment": fragment},
        )
    if _AMBIGUOUS_HEIGHT.search(fragment):
        raise HouseTextError(
            "ambiguous_height",
            "say explicitly that the height is the floor height, e.g. 'высота этажа 3 м'",
            {"fragment": fragment},
        )
    raise HouseTextError(
        "unknown_clause", f"could not understand '{fragment}'", {"fragment": fragment}
    )


def _clause(language: Language, clause: str, out: _Collector) -> None:
    for name, pattern in _COMPILED[language]:
        match = pattern.fullmatch(clause)
        if match is None:
            continue
        handlers: dict[str, Callable[[re.Match[str]], None]] = {
            "footprint": lambda m: _footprint(m, clause, out),
            "floors": lambda m: out.put(
                "floors", _floor_count(m.group("n") or m.group("m")), clause
            ),
            "shape": lambda _m: out.put("shape", "rectangle", clause),
        }
        if name in handlers:
            handlers[name](match)
        else:
            group = "v" if match.group("v") is not None else "w"
            out.put(
                name,
                _millimetres(match.group(group), match.group(f"{group}_u"), name, clause),
                clause,
            )
        return
    _refuse_unknown(clause)


def _footprint(match: re.Match[str], clause: str, out: _Collector) -> None:
    second_unit = match.group("b_u")
    if second_unit is None:
        _millimetres(match.group("b"), None, "width_mm", clause)
    first_unit = match.group("a_u") or second_unit
    out.put("length_mm", _millimetres(match.group("a"), first_unit, "length_mm", clause), clause)
    out.put("width_mm", _millimetres(match.group("b"), second_unit, "width_mm", clause), clause)


def parse_house_text(prompt: str) -> ParsedHouseText:
    """Parse one bounded house description or raise ``HouseTextError``; never guesses."""
    text = _normalise(prompt)
    language: Language | None = None
    head: re.Match[str] | None = None
    candidates: tuple[Language, ...] = ("ru", "en")
    for candidate in candidates:
        head = _HEADS[candidate].fullmatch(text)
        if head is not None:
            language = candidate
            break
    if head is None or language is None:
        raise HouseTextError(
            "not_a_house",
            "start with a house description, e.g. 'Создай дом …' or 'Build a house …'",
        )
    out = _Collector()
    for token in head.group("mods").split():
        _modifier(language, token, out)
    rest = head.group("rest").strip()
    rest = _CONNECTIVE.sub("", re.sub(r"^[,;:]\s*", "", rest))
    if rest:
        for raw in _SPLIT.split(rest):
            clause = _CONNECTIVE.sub("", raw.strip()).strip()
            if not clause:
                raise HouseTextError("unknown_clause", "empty clause in the description")
            _clause(language, clause, out)

    missing = [name for name in REQUIRED if name not in out.values]
    if missing:
        raise HouseTextError(
            "missing_fields",
            "the description must state length, width, floor height and number of floors",
            {"missing": missing},
        )
    for name, (low, high) in BOUNDS.items():
        value = out.values[name]
        assert isinstance(value, int)
        if not low <= value <= high:
            raise HouseTextError(
                "out_of_range",
                f"{name} must be between {low} and {high}",
                {"field": name, "value": value, "min": low, "max": high},
            )
    return ParsedHouseText(
        language=language,
        length_mm=int(out.values["length_mm"]),
        width_mm=int(out.values["width_mm"]),
        floor_height_mm=int(out.values["floor_height_mm"]),
        floors=int(out.values["floors"]),
        shape="rectangle",
        sources=dict(out.sources),
    )
