from __future__ import annotations

import pytest

from app.api.errors import ValidationFailedError
from app.services.animation_commands import parse_duration
from app.services.scene_animations import mechanism_animation

HINGE = {
    "kind": "hinged_lid",
    "joint": {
        "type": "revolute",
        "node_id": "lid",
        "axis": "x",
        "min_angle_deg": 0,
        "max_angle_deg": 110,
    },
}


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("animate the lid in 2.5 seconds", (2.5, "en")),
        ("Animate mechanism over 1 sec.", (1.0, "en")),
        ("анимируй крышку за 2,5 секунды", (2.5, "ru")),
    ],
)
def test_bounded_animation_command_parser(prompt: str, expected: tuple[float, str]) -> None:
    assert parse_duration(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "make it dance",
        "open and close the lid",
        "animate the lid in 0 seconds",
        "animate the lid in 61 seconds",
    ],
)
def test_animation_command_parser_refuses_unsupported_or_unbounded_text(prompt: str) -> None:
    with pytest.raises(ValidationFailedError):
        parse_duration(prompt)


def test_clip_duration_is_trusted_only_when_bound_to_the_exact_joint() -> None:
    provenance = {
        "build_hinged_lid": HINGE,
        "animation_clip": {
            "schema_version": 1,
            "kind": "rigid_joint_clip",
            "joint_type": "revolute",
            "node_id": "lid",
            "duration_seconds": 2.5,
        },
    }
    animation = mechanism_animation(provenance, {"lid"})
    assert animation is not None and animation["duration_seconds"] == 2.5
    for forged in (
        {**provenance["animation_clip"], "node_id": "base"},
        {**provenance["animation_clip"], "joint_type": "prismatic"},
        {**provenance["animation_clip"], "duration_seconds": 0},
    ):
        assert mechanism_animation({**provenance, "animation_clip": forged}, {"lid"}) is None
