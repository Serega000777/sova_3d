"""Durable job records (docs/03 §5): enqueue, look up, and terminal transitions.

State changes go through the DB trigger from migration 0003 (terminal states
are final, progress is monotonic); this module only decides *what* to write.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import observability
from app.api.errors import ConflictError, NotFoundError
from app.models.core import WorkspaceRole
from app.models.execution import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    FailureClass,
    Job,
    JobStatus,
)
from app.services.authz import require_workspace_role

# How long a job of each type may run before the platform calls it stuck (T-095).
# Generous: these are wall clocks for a hung worker, not performance targets.
TIMEOUTS_SECONDS: dict[str, int] = {
    "repair": 600,
    "ai_command": 900,
    "manual_edit": 600,
    "analyze_print": 900,
    "optimize_print": 1800,
    "export": 600,
    "reconstruct_scan": 3600,
}
DEFAULT_TIMEOUT_SECONDS = 900


def enqueue(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_type: str,
    input: dict[str, Any],
    created_by: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    project_version_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    """Create a queued job. With an Idempotency-Key the existing job is returned."""
    if idempotency_key:
        existing = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace_id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
    job = Job(
        workspace_id=workspace_id,
        type=job_type,
        input=input,
        created_by=created_by,
        project_id=project_id,
        project_version_id=project_version_id,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        timeout_seconds=TIMEOUTS_SECONDS.get(job_type, DEFAULT_TIMEOUT_SECONDS),
        trace_id=observability.trace_id(),
    )
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, *, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("job", job_id)
    require_workspace_role(db, user_id, job.workspace_id, WorkspaceRole.viewer)
    return job


def claim_next(db: Session, job_types: frozenset[str] | None = None) -> Job | None:
    """Atomically take the oldest queued job (FOR UPDATE SKIP LOCKED) and mark it running."""
    stmt = (
        sa.select(Job)
        .where(Job.status == JobStatus.queued)
        .order_by(Job.created_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job_types:
        stmt = stmt.where(Job.type.in_(job_types))
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = JobStatus.running
    job.stage = "claimed"
    db.flush()
    db.refresh(job)
    return job


def set_progress(db: Session, job: Job, percent: int, stage: str) -> None:
    job.progress = max(min(percent, 100), job.progress)
    job.stage = stage
    db.flush()


def wait_for_input(db: Session, job: Job, result: dict[str, Any]) -> None:
    """Park a running job until a user supplies what it asked for (clarifications)."""
    job.result = result
    job.stage = "waiting_input"
    job.status = JobStatus.waiting_input
    db.flush()
    db.refresh(job)


def succeed(db: Session, job: Job, result: dict[str, Any]) -> None:
    job.result = result
    job.error = None
    job.status = JobStatus.succeeded
    db.flush()
    db.refresh(job)  # finished_at / progress=100 are stamped by the DB trigger


def fail(
    db: Session,
    job: Job,
    *,
    code: str,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> None:
    """Fail the job, or requeue it when the failure is retryable and attempts remain."""
    job.error = {"code": code, "message": message, "details": details or {}}
    job.failure_class = FailureClass.retryable if retryable else FailureClass.permanent
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.stage = "retry_scheduled"
    else:
        job.status = JobStatus.failed
    db.flush()
    db.refresh(job)


def is_active(job: Job) -> bool:
    return job.status in ACTIVE_JOB_STATUSES


class JobCanceledError(Exception):
    """Raised inside a handler at the next checkpoint after a cancel was requested."""


def request_cancel(db: Session, *, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """T-095: ask a job to stop. Queued work stops now; running work stops at its next
    checkpoint, so a half-written model is never committed."""
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("job", job_id)
    require_workspace_role(db, user_id, job.workspace_id, WorkspaceRole.editor)
    if job.status in TERMINAL_JOB_STATUSES:
        raise ConflictError("this job has already finished", {"status": job.status.value})
    job.cancel_requested = True
    if job.status in (JobStatus.queued, JobStatus.waiting_input):
        job.status = JobStatus.canceled
        job.stage = "canceled"
        job.error = {"code": "canceled", "message": "canceled before it started", "details": {}}
    db.flush()
    db.refresh(job)
    return job


def cancel(db: Session, job: Job, *, reason: str = "canceled at the user's request") -> None:
    """Write the terminal state for a job that stopped itself."""
    job.status = JobStatus.canceled
    job.stage = "canceled"
    job.error = {"code": "canceled", "message": reason, "details": {}}
    db.flush()
    db.refresh(job)


def reap_stale(db: Session, *, now: datetime | None = None) -> list[Job]:
    """Fail jobs whose worker died mid-run (T-095).

    A running job past its timeout has no one watching it: the process is gone, or it is
    wedged. It is retryable, so the normal attempt budget decides whether it runs again.
    """
    now = now or datetime.now(UTC)
    stale = db.scalars(
        sa.select(Job).where(Job.status == JobStatus.running, Job.started_at.is_not(None))
    ).all()
    reaped: list[Job] = []
    for job in stale:
        started = job.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if now - started <= timedelta(seconds=job.timeout_seconds):
            continue
        fail(
            db,
            job,
            code="job_timeout",
            message=f"no progress for more than {job.timeout_seconds} s",
            retryable=True,
            details={"timeout_seconds": job.timeout_seconds},
        )
        reaped.append(job)
    return reaped
