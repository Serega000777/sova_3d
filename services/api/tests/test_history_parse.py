"""T-122 (F-016): what "верни как было два часа назад" means, deterministically."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.services.history import parse_rollback


@pytest.mark.parametrize(
    ("prompt", "kind", "value"),
    [
        ("верни как было два часа назад", "time", timedelta(hours=2)),
        ("верни как было 2 часа назад", "time", timedelta(hours=2)),
        ("undo the last two hours", "steps", 1),  # no "ago": a plain undo
        ("go back three days ago", "time", timedelta(days=3)),
        ("верни как было десять минут назад", "time", timedelta(minutes=10)),
        ("верни полтора часа назад", "time", timedelta(minutes=90)),
        ("go back 30 minutes ago", "time", timedelta(minutes=30)),
        ("undo what I did an hour ago", "time", timedelta(hours=1)),
        ("верни полчаса назад", "time", timedelta(minutes=30)),
        ("верни как было неделю назад", "time", timedelta(days=7)),
        ("undo what I did a week ago", "time", timedelta(days=7)),
        ("откати на вчера", "time", timedelta(days=1)),
        ("restore yesterday's version", "time", timedelta(days=1)),
        ("верни к версии 3", "version", 3),
        ("go back to v2", "version", 2),
        ("revert to version 5", "version", 5),
        ("верни как было до отверстия", "before", "отверстия"),
        ("undo everything before the hole", "before", "hole"),
        ("отмени последние 2 изменения", "steps", 2),
        ("undo the last 3 changes", "steps", 3),
        ("верни как было", "steps", 1),
        ("undo", "steps", 1),
        ("откати", "steps", 1),
    ],
)
def test_rollback_sentences_resolve_to_one_intent(prompt: str, kind: str, value: object) -> None:
    intent = parse_rollback(prompt)
    assert intent is not None and intent.kind == kind
    if kind == "time" and value is not None:
        assert intent.delta == value
    elif kind == "version":
        assert intent.version_no == value
    elif kind == "before":
        assert intent.word == value
    elif kind == "steps":
        assert intent.steps == value


@pytest.mark.parametrize(
    "prompt",
    [
        "Органайзер 200×100×50 мм с 6 секциями",
        "drill a 5 mm hole",
        "a bracket with a back plate 40x20x3 mm",
        "сделай стенки толще",
    ],
)
def test_ordinary_requests_are_not_rollbacks(prompt: str) -> None:
    assert parse_rollback(prompt) is None


# --- resolving against a lineage -----------------------------------------------------------


class _Line:
    """A three-version project in memory: v1 at t0, v2 an hour later, v3 two hours later."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        from app.models.versioning import ProjectVersion, VersionState

        self.t0 = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
        self.versions = []
        parent = None
        for number, label in ((1, "Plate"), (2, "drill a hole"), (3, "resize")):
            version = ProjectVersion(
                id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                parent_version_id=parent.id if parent else None,
                sequence_no=number,
                state=VersionState.finalized,
                label=label,
                provenance={"plan_goal": label},
            )
            version.created_at = self.t0 + timedelta(hours=number - 1)
            self.versions.append(version)
            parent = version
        self.by_id = {v.id: v for v in self.versions}

    def get(self, _model: object, key: uuid.UUID) -> object:
        return self.by_id.get(key)

    @property
    def head(self) -> object:
        return self.versions[-1]


def test_time_travel_picks_the_latest_version_before_the_cutoff() -> None:
    from app.services.history import resolve_target

    line = _Line()
    now = line.t0 + timedelta(hours=2, minutes=30)
    for expression, expected in (
        ("верни как было полтора часа назад", 2),  # cutoff t0+1h: v2 was made right then
        ("go back 2.5 hours ago", 1),
        ("верни как было 3 часа назад", None),
    ):
        intent = parse_rollback(expression)
        assert intent is not None and intent.kind == "time"
        found, how = resolve_target(line, line.head, intent, now)  # type: ignore[arg-type]
        assert (found.sequence_no if found else None) == expected, (expression, how)


def test_before_a_word_finds_the_version_that_introduced_it() -> None:
    from app.services.history import resolve_target

    line = _Line()
    intent = parse_rollback("верни как было до отверстия")
    assert intent is not None
    found, how = resolve_target(line, line.head, intent)  # type: ignore[arg-type]
    assert found is not None and found.sequence_no == 1 and "v2" in how
    intent = parse_rollback("undo everything before the fillet")
    assert intent is not None
    found, how = resolve_target(line, line.head, intent)  # type: ignore[arg-type]
    assert found is None and "nothing" in how
