"""AI History (T-122/T-123, F-016): "верни как было два часа назад".

Nothing is ever deleted: a rollback is a new version on top of the head that carries the
restored version's assets and operation log, so the project keeps one honest line of
history and the way back is itself a version. The sentence is resolved deterministically
— steps, a clock time, a version number, or "before <word>" — and the resolution is
recorded in the provenance so the user can see what "two hours ago" meant.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Operation
from app.models.versioning import ProjectVersion, VersionState
from app.services import projects
from app.services.authz import require_workspace_role

ROLLBACK_JOB = "rollback"

Kind = Literal["steps", "time", "version", "before"]


@dataclass(frozen=True)
class RollbackIntent:
    kind: Kind
    steps: int = 1
    delta: timedelta | None = None
    version_no: int | None = None
    word: str | None = None


_CUES = (
    "верни",
    "вернут",
    "верните",
    "откат",
    "откати",
    "отмени",
    "как было",
    "undo",
    "revert",
    "roll back",
    "rollback",
    "go back",
    "restore",
    "back to",
)
_VERSION = re.compile(r"(?:верси\w*|version|\bv)\s*(\d+)\b", re.IGNORECASE)
_STEPS = re.compile(
    r"(?:последн\w*|last)\s*(\d+)|(\d+)\s*(?:шаг\w*|измен\w*|steps?|changes?|edits?)",
    re.IGNORECASE,
)
# "два часа назад": people say numbers in words far more often than in digits.
_NUMBER_WORDS: dict[str, float] = {
    "один": 1,
    "одну": 1,
    "одного": 1,
    "одной": 1,
    "one": 1,
    "an": 1,
    "a": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "two": 2,
    "пару": 2,
    "couple of": 2,
    "три": 3,
    "трёх": 3,
    "трех": 3,
    "three": 3,
    "четыре": 4,
    "четырёх": 4,
    "four": 4,
    "пять": 5,
    "пяти": 5,
    "five": 5,
    "шесть": 6,
    "six": 6,
    "семь": 7,
    "seven": 7,
    "восемь": 8,
    "eight": 8,
    "девять": 9,
    "nine": 9,
    "десять": 10,
    "десяти": 10,
    "ten": 10,
    "пятнадцать": 15,
    "fifteen": 15,
    "двадцать": 20,
    "twenty": 20,
    "тридцать": 30,
    "thirty": 30,
    "сорок": 40,
    "forty": 40,
    "полчаса": 0.5,
    "half an hour": 0.5,
    "полтора": 1.5,
}
_AMOUNT = "|".join(re.escape(word) for word in sorted(_NUMBER_WORDS, key=len, reverse=True))
# "два часа назад", "an hour ago", "неделю назад" (no amount: one of the unit).
_AGO = re.compile(
    r"(?:(\d+(?:[.,]\d+)?|" + _AMOUNT + r")\s*)?"
    r"(минут\w*|час\w*|дн\w*|день|недел\w*|min\w*|hours?|days?|weeks?)\s*(?:назад|ago|тому)",
    re.IGNORECASE,
)
_BEFORE = re.compile(
    r"(?:до того как|до|before)\s+(?:the |a |я |мы )?"
    r"(?:добавил\w*|сделал\w*|added|made|drilled|cut)?\s*"
    r"([a-zA-Zа-яА-ЯёЁ][\w-]{2,})",
    re.IGNORECASE,
)
# "полчаса назад" / "полтора часа назад" / "half an hour ago": the amount is the unit.
_HALF = re.compile(
    r"(полчаса|полтора|half an hour)\s*(час\w*|hour)?\s*(?:назад|ago|тому)", re.IGNORECASE
)
_UNIT_SECONDS = {
    "мин": 60,
    "min": 60,
    "час": 3600,
    "hour": 3600,
    "дн": 86400,
    "день": 86400,
    "day": 86400,
    "недел": 7 * 86400,
    "week": 7 * 86400,
}


def parse_rollback(prompt: str) -> RollbackIntent | None:
    """The rollback a sentence asks for, or None when it is not a rollback at all."""
    lowered = prompt.lower().strip()
    if not any(cue in lowered for cue in _CUES):
        return None

    version = _VERSION.search(lowered)
    if version:
        return RollbackIntent(kind="version", version_no=int(version.group(1)))

    ago = _HALF.search(lowered) or _AGO.search(lowered)
    if ago:
        amount_text = (ago.group(1) or "").lower()
        unit = (ago.group(2) or "час").lower()
        if not amount_text:
            amount = 1.0
        elif amount_text in _NUMBER_WORDS:
            amount = _NUMBER_WORDS[amount_text]
        else:
            amount = float(amount_text.replace(",", "."))
        seconds = next((s for key, s in _UNIT_SECONDS.items() if unit.startswith(key)), 3600)
        return RollbackIntent(kind="time", delta=timedelta(seconds=amount * seconds))
    if "вчера" in lowered or "yesterday" in lowered:
        return RollbackIntent(kind="time", delta=timedelta(days=1))
    if "позавчера" in lowered:
        return RollbackIntent(kind="time", delta=timedelta(days=2))
    if "на прошлой неделе" in lowered or "last week" in lowered:
        return RollbackIntent(kind="time", delta=timedelta(days=7))

    before = _BEFORE.search(lowered)
    if before and before.group(1) not in ("того", "как", "было", "this", "that", "it"):
        return RollbackIntent(kind="before", word=before.group(1))

    steps = _STEPS.search(lowered)
    if steps:
        return RollbackIntent(kind="steps", steps=int(steps.group(1) or steps.group(2)))
    return RollbackIntent(kind="steps", steps=1)


def _lineage(db: Session, head: ProjectVersion) -> list[ProjectVersion]:
    """The head and its ancestors, newest first."""
    line: list[ProjectVersion] = [head]
    seen = {head.id}
    current = head
    while current.parent_version_id is not None and current.parent_version_id not in seen:
        parent = db.get(ProjectVersion, current.parent_version_id)
        if parent is None:
            break
        line.append(parent)
        seen.add(parent.id)
        current = parent
    return line


# The change may have been asked for in the other language.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "отвер": ("hole", "add_hole"),
    "дыр": ("hole", "add_hole"),
    "hole": ("отверст", "add_hole"),
    "скруг": ("fillet", "round"),
    "fille": ("скругл",),
    "round": ("скругл", "fillet"),
    "карма": ("pocket", "cut"),
    "pocke": ("карман",),
    "выст": ("boss", "pad"),
    "boss": ("выступ", "прилив"),
    "разме": ("resize", "set_dimensions"),
    "resiz": ("размер", "set_dimensions"),
    "size": ("размер", "set_dimensions"),
    "краск": ("paint",),
    "paint": ("краск",),
}


def _mentions(version: ProjectVersion, word: str) -> bool:
    stem = word.lower()[:5]
    stems = {stem, *_SYNONYMS.get(stem, ())}
    haystack = " ".join(
        [
            version.label or "",
            str((version.provenance or {}).get("plan_goal") or ""),
            " ".join(
                str(op.get("type", ""))
                for op in (version.provenance or {}).get("edit_operations") or []
            ),
            str((version.provenance or {}).get("operation") or ""),
        ]
    ).lower()
    return any(candidate in haystack for candidate in stems)


def resolve_target(
    db: Session, head: ProjectVersion, intent: RollbackIntent, now: datetime | None = None
) -> tuple[ProjectVersion | None, str]:
    """The version the sentence points at, and how it was chosen (for the provenance)."""
    line = _lineage(db, head)
    if intent.kind == "version":
        found = next((v for v in line if v.sequence_no == intent.version_no), None)
        if found is None:
            found = db.scalar(
                sa.select(ProjectVersion).where(
                    ProjectVersion.project_id == head.project_id,
                    ProjectVersion.sequence_no == intent.version_no,
                    ProjectVersion.state == VersionState.finalized,
                )
            )
        return found, f"version {intent.version_no}"
    if intent.kind == "time":
        assert intent.delta is not None
        cutoff = (now or datetime.now(UTC)) - intent.delta
        found = next((v for v in line if v.created_at <= cutoff), None)
        return found, f"the latest version before {cutoff.isoformat(timespec='minutes')}"
    if intent.kind == "before":
        assert intent.word is not None
        # "before the hole" means before the hole first appeared: the oldest mention's parent
        for index in range(len(line) - 1, -1, -1):
            if _mentions(line[index], intent.word):
                if index + 1 < len(line):
                    return line[index + 1], f"before '{intent.word}' (v{line[index].sequence_no})"
                return (
                    None,
                    f"'{intent.word}' was there from the start (v{line[index].sequence_no})",
                )
        return None, f"nothing in the history mentions '{intent.word}'"
    steps = max(intent.steps, 1)
    found = line[steps] if steps < len(line) else None
    return found, f"{steps} change(s) back"


def rollback(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    expression: str,
    now: datetime | None = None,
) -> ProjectVersion:
    """Make an earlier state the current one — as a new version, never by deleting."""
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if project.head_version_id is None:
        raise ValidationFailedError("the project has no versions to go back to")
    head = db.get(ProjectVersion, project.head_version_id)
    assert head is not None

    intent = parse_rollback(expression) or parse_rollback("верни " + expression)
    assert intent is not None
    target, how = resolve_target(db, head, intent, now)
    if target is None:
        raise ValidationFailedError(
            "there is no version that far back",
            {"expression": expression, "how": how, "versions": len(_lineage(db, head))},
        )
    if target.id == head.id:
        raise ValidationFailedError(
            "that is already the current version",
            {"expression": expression, "how": how, "version": target.sequence_no},
        )

    assets = {link.role: link.asset_id for link in target.assets}
    restored_provenance = target.provenance or {}
    provenance: dict[str, Any] = {
        "operation": "rollback",
        "restored_version_id": str(target.id),
        "restored_sequence_no": target.sequence_no,
        "expression": expression,
        "how": how,
        "from_version_id": str(head.id),
    }
    for key in ("bodies", "kernel", "paint", "plan_goal"):
        if restored_provenance.get(key) is not None:
            provenance[key] = restored_provenance[key]
    version = projects.create_version_internal(
        db,
        project_id=project.id,
        parent_version_id=head.id,
        label=f"Back to v{target.sequence_no}" + (f" · {target.label}" if target.label else ""),
        provenance=provenance,
        assets=assets,
        finalize=False,
        created_by=user_id,
    )
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == target.id)
        .order_by(Operation.sequence_no)
    ).all()
    for row in rows:
        db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=row.sequence_no,
                operation_type=row.operation_type,
                schema_version=row.schema_version,
                params=row.params,
                entity_refs=row.entity_refs,
            )
        )
    db.flush()
    projects.finalize_version(db, version)
    return version
