"""Strict text commands for one trusted rigid mechanism animation clip."""

from __future__ import annotations

import re

from app.api.errors import ValidationFailedError

_EN = re.compile(
    r"^\s*animate\s+(?:the\s+)?(?:lid|mechanism)\s+(?:in|over|for)\s+"
    r"(?P<duration>\d+(?:[.,]\d+)?)\s*(?:s|sec|secs|second|seconds)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_RU = re.compile(
    r"^\s*анимируй\s+(?:крышку|механизм)\s+за\s+"
    r"(?P<duration>\d+(?:[.,]\d+)?)\s*(?:с|сек|секунд[уы]?)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def parse_duration(prompt: str) -> tuple[float, str]:
    """Parse the bounded whole-joint clip command without guessing intent."""

    match = _EN.fullmatch(prompt) or _RU.fullmatch(prompt)
    if match is None:
        raise ValidationFailedError(
            "unsupported animation command; use ‘animate the lid in 2 seconds’ or "
            "‘анимируй крышку за 2 секунды’"
        )
    duration = float(match.group("duration").replace(",", "."))
    if not 0.1 <= duration <= 60:
        raise ValidationFailedError("animation duration must be between 0.1 and 60 seconds")
    language = "ru" if match.re is _RU else "en"
    return duration, language
