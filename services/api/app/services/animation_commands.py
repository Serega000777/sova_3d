"""Strict text commands for one trusted rigid mechanism animation clip."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.api.errors import ValidationFailedError

_EN = re.compile(
    r"^\s*(?P<verb>animate|open|close)\s+(?:the\s+)?(?:lid|mechanism)\s+(?:in|over|for)\s+"
    r"(?P<duration>\d+(?:[.,]\d+)?)\s*(?:s|sec|secs|second|seconds)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_RU = re.compile(
    r"^\s*(?P<verb>анимируй|открой|закрой)\s+(?:крышку|механизм)\s+за\s+"
    r"(?P<duration>\d+(?:[.,]\d+)?)\s*(?:с|сек|секунд[уы]?)\s*[.!]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedAnimationCommand:
    duration_seconds: float
    direction: Literal["forward", "reverse"]
    language: Literal["ru", "en"]


def parse_command(prompt: str) -> ParsedAnimationCommand:
    """Parse one bounded whole-joint clip without guessing motion or timing."""

    match = _EN.fullmatch(prompt) or _RU.fullmatch(prompt)
    if match is None:
        raise ValidationFailedError(
            "unsupported animation command; use ‘open the lid in 2 seconds’, "
            "‘close the lid in 2 seconds’, ‘открой крышку за 2 секунды’ or "
            "‘закрой крышку за 2 секунды’"
        )
    duration = float(match.group("duration").replace(",", "."))
    if not 0.1 <= duration <= 60:
        raise ValidationFailedError("animation duration must be between 0.1 and 60 seconds")
    language: Literal["ru", "en"] = "ru" if match.re is _RU else "en"
    verb = match.group("verb").lower()
    direction: Literal["forward", "reverse"] = (
        "reverse" if verb in {"close", "закрой"} else "forward"
    )
    return ParsedAnimationCommand(duration, direction, language)


def parse_duration(prompt: str) -> tuple[float, str]:
    """Compatibility wrapper for the original duration-only parser contract."""

    command = parse_command(prompt)
    return command.duration_seconds, command.language
