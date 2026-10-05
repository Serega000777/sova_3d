"""Privacy-minimised candidate dataset export (self-learning plan, step 3).

The exporter is deliberately operator-only: there is no HTTP route that can disclose prompts or
model outputs.  It exports only projects whose *current* consent snapshot is enabled, so revoking
consent removes the whole project from every future export.

Identifiers are replaced with keyed HMACs and common direct identifiers are redacted from free
text.  Automatic redaction cannot prove that arbitrary prose contains no personal information,
therefore every export is labelled ``privacy_review_required`` and must be reviewed before it is
used for training.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.core import Project
from app.models.execution import AIRequest, Job
from app.models.feedback import AIFeedback
from app.models.training_consent import ProjectTrainingConsent

SCHEMA_VERSION = "sova.training-candidate.v1"
RECONSTRUCTION_JOB_TYPES = frozenset({"reconstruct_scan", "generate_mesh"})

_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){7,15}(?!\w)")
_UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^/\s]+/)+[^/\s]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<!\w)[a-z]:\\(?:[^\\\s]+\\)+[^\\\s]+")
_UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)
_SENSITIVE_KEY_PARTS = frozenset(
    {"email", "phone", "address", "filename", "file_name", "display_name", "source_url"}
)


@dataclass(frozen=True, slots=True)
class ExportSummary:
    destination: Path
    ai_request_samples: int
    reconstruction_samples: int

    @property
    def total_samples(self) -> int:
        return self.ai_request_samples + self.reconstruction_samples


def _pseudonym(secret: bytes, kind: str, value: object) -> str:
    digest = hmac.new(secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
    return digest[:32]


def _redact_text(value: str, secret: bytes) -> str:
    value = _EMAIL_RE.sub("[EMAIL]", value)
    value = _URL_RE.sub("[URL]", value)
    value = _IPV4_RE.sub("[IP]", value)
    value = _PHONE_RE.sub("[PHONE]", value)
    value = _UNIX_PATH_RE.sub("[PATH]", value)
    value = _WINDOWS_PATH_RE.sub("[PATH]", value)
    return _UUID_RE.sub(
        lambda match: f"[ID:{_pseudonym(secret, 'embedded', match.group(0))}]", value
    )


def _safe_value(value: Any, secret: bytes, *, key: str | None = None) -> Any:
    """Return JSON-safe data with direct identifiers removed or pseudonymised."""
    key_lower = (key or "").lower()
    if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]" if value is not None else None
    if isinstance(value, uuid.UUID):
        return _pseudonym(secret, key_lower or "uuid", value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        if key_lower.endswith("_id"):
            return _pseudonym(secret, key_lower, value)
        return _redact_text(value, secret)
    if isinstance(value, dict):
        return {
            _redact_text(str(item_key), secret): _safe_value(item, secret, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, secret) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value), secret)


def _feedback_payload(rows: Iterable[AIFeedback], secret: bytes) -> list[dict[str, Any]]:
    return [
        {
            "feedback_key": _pseudonym(secret, "feedback", row.id),
            "rating": row.rating.value,
            "reason": row.reason.value if row.reason else None,
            "event_date": row.created_at.astimezone(UTC).date().isoformat(),
        }
        for row in sorted(rows, key=lambda item: (item.created_at, item.id))
    ]


def _consented_project_ids(db: Session) -> tuple[uuid.UUID, ...]:
    """Lock consent/project rows for a consistent export snapshot.

    A concurrent revoke waits for the export transaction to finish and therefore applies to the
    next export; it can never split one export into a mixture of pre/post-revocation queries.
    """
    return tuple(
        db.scalars(
            sa.select(Project.id)
            .join(ProjectTrainingConsent, ProjectTrainingConsent.project_id == Project.id)
            .where(ProjectTrainingConsent.enabled.is_(True), Project.deleted_at.is_(None))
            .order_by(Project.id)
            .with_for_update(of=(Project, ProjectTrainingConsent))
        )
    )


def build_candidate_dataset(
    db: Session, *, secret: bytes, generated_at: datetime | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a deterministic-in-content candidate dataset from current consent snapshots."""
    if len(secret) < 32:
        raise ValueError("training dataset hash secret must be at least 32 bytes")

    consented = _consented_project_ids(db)
    feedback_rows = list(
        db.scalars(
            sa.select(AIFeedback)
            .where(AIFeedback.project_id.in_(consented))
            .order_by(AIFeedback.created_at, AIFeedback.id)
        )
    )
    by_request: dict[uuid.UUID, list[AIFeedback]] = defaultdict(list)
    by_job: dict[uuid.UUID, list[AIFeedback]] = defaultdict(list)
    by_version: dict[uuid.UUID, list[AIFeedback]] = defaultdict(list)
    for row in feedback_rows:
        if row.ai_request_id:
            by_request[row.ai_request_id].append(row)
        if row.job_id:
            by_job[row.job_id].append(row)
        if row.version_id:
            by_version[row.version_id].append(row)

    samples: list[dict[str, Any]] = []
    requests = list(
        db.scalars(
            sa.select(AIRequest)
            .where(AIRequest.project_id.in_(consented))
            .order_by(AIRequest.created_at, AIRequest.id)
        )
    )
    for request in requests:
        ratings = list(by_request.get(request.id, ()))
        if request.result_version_id:
            ratings.extend(by_version.get(request.result_version_id, ()))
        ratings = list({row.id: row for row in ratings}.values())
        samples.append(
            {
                "record_type": "sample",
                "schema_version": SCHEMA_VERSION,
                "sample_type": "ai_request",
                "sample_key": _pseudonym(secret, "ai_request", request.id),
                "project_key": _pseudonym(secret, "project", request.project_id),
                "event_date": request.created_at.astimezone(UTC).date().isoformat(),
                "input": {
                    "prompt": _redact_text(request.prompt, secret),
                    "context": _safe_value(request.context, secret),
                },
                "output": {
                    "provider": request.provider,
                    "model": request.model,
                    "status": request.status.value,
                    "safety_state": request.safety_state.value,
                    "plan": _safe_value(request.output_plan, secret),
                    "plan_errors": _safe_value(request.plan_errors, secret),
                },
                "result": {
                    "version_key": (
                        _pseudonym(secret, "version", request.result_version_id)
                        if request.result_version_id
                        else None
                    )
                },
                "feedback": _feedback_payload(ratings, secret),
            }
        )

    jobs = list(
        db.scalars(
            sa.select(Job)
            .where(
                Job.project_id.in_(consented),
                Job.type.in_(RECONSTRUCTION_JOB_TYPES),
            )
            .order_by(Job.created_at, Job.id)
        )
    )
    for job in jobs:
        ratings = list(by_job.get(job.id, ()))
        result_version_id: uuid.UUID | None = None
        raw_version_id = (job.result or {}).get("version_id")
        if raw_version_id:
            try:
                result_version_id = uuid.UUID(str(raw_version_id))
            except ValueError:
                result_version_id = None
        if result_version_id:
            ratings.extend(by_version.get(result_version_id, ()))
        ratings = list({row.id: row for row in ratings}.values())
        samples.append(
            {
                "record_type": "sample",
                "schema_version": SCHEMA_VERSION,
                "sample_type": "reconstruction",
                "sample_key": _pseudonym(secret, "job", job.id),
                "project_key": _pseudonym(secret, "project", job.project_id),
                "event_date": job.created_at.astimezone(UTC).date().isoformat(),
                "input": {"job_type": job.type, "payload": _safe_value(job.input, secret)},
                "output": {
                    "status": job.status.value,
                    "result": _safe_value(job.result, secret),
                    "error": _safe_value(job.error, secret),
                },
                "result": {
                    "version_key": (
                        _pseudonym(secret, "version", result_version_id)
                        if result_version_id
                        else None
                    )
                },
                "feedback": _feedback_payload(ratings, secret),
            }
        )

    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    counts = {
        "ai_request": sum(sample["sample_type"] == "ai_request" for sample in samples),
        "reconstruction": sum(sample["sample_type"] == "reconstruction" for sample in samples),
    }
    manifest = {
        "record_type": "manifest",
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "sample_counts": counts,
        "privacy": {
            "project_consent": "current_opt_in_only",
            "identifiers": "hmac_sha256",
            "direct_identifier_redaction": True,
            "privacy_review_required": True,
        },
    }
    return manifest, samples


def export_candidate_dataset(
    db: Session,
    *,
    destination: Path,
    secret: bytes,
    generated_at: datetime | None = None,
) -> ExportSummary:
    """Atomically write a mode-0600 JSONL export; never emit dataset rows to stdout."""
    manifest, samples = build_candidate_dataset(db, secret=secret, generated_at=generated_at)
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in (manifest, *samples):
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return ExportSummary(
        destination=destination,
        ai_request_samples=manifest["sample_counts"]["ai_request"],
        reconstruction_samples=manifest["sample_counts"]["reconstruction"],
    )
