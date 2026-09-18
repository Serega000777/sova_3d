"""Job runner (worker-general process): claim -> execute handler -> persist outcome.

`execute()` is transaction-agnostic so tests can drive it with their own
session; `serve()` is the production loop with one session per job and a
commit after every state change, so pollers see progress as it happens.
Start it with `python -m app.jobs` (never `-m app.jobs.runner`: running this
module as __main__ would import a second copy and split the handler registry).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app import observability
from app.config import Settings, load_settings
from app.db import make_engine, make_session_factory
from app.models.execution import Job
from app.services import jobs
from app.storage import ObjectStorage, S3Storage

log = logging.getLogger("app.jobs")


class JobFailureError(Exception):
    """Raised by handlers for a structured failure; anything else is an unexpected crash."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


class JobWaitingForInputError(Exception):
    """Raised by a handler to park the job in waiting_input (docs/03 §5) with a result payload
    describing what it needs; a later request requeues the job."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("waiting for input")
        self.result = result


@dataclass(slots=True)
class JobContext:
    db: Session
    storage: ObjectStorage
    job: Job
    commit: Callable[[], None]

    def progress(self, percent: int, stage: str) -> None:
        """Report progress — and stop here if the job was canceled or has run too long.

        Every handler reports progress between steps, which makes these the safe points
        to stop at: nothing is half-written, and the worker is never killed (T-095).
        """
        self.check_still_wanted()
        jobs.set_progress(self.db, self.job, percent, stage)
        self.commit()

    def check_still_wanted(self) -> None:
        self.db.refresh(self.job, ["cancel_requested"])
        if self.job.cancel_requested:
            raise jobs.JobCanceledError("canceled at the user's request")
        started = self.job.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if datetime.now(UTC) - started > timedelta(seconds=self.job.timeout_seconds):
                raise JobFailureError(
                    "job_timeout",
                    f"this job exceeded its {self.job.timeout_seconds} s budget",
                    retryable=True,
                    details={"timeout_seconds": self.job.timeout_seconds},
                )


class Handler(Protocol):
    def __call__(self, ctx: JobContext) -> dict[str, Any]: ...


HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        HANDLERS[job_type] = handler
        return handler

    return decorator


def execute(db: Session, storage: ObjectStorage, job: Job, *, commit: Callable[[], None]) -> Job:
    """Run the handler for an already-claimed (running) job and persist the outcome.

    Everything logged inside carries the job's ids and the trace id of the request that
    queued it, so one id follows a click all the way through the worker (T-096).
    """
    with observability.bind(
        trace_id=job.trace_id,
        job_id=str(job.id),
        job_type=job.type,
        workspace_id=str(job.workspace_id),
    ):
        return _execute(db, storage, job, commit=commit)


def _execute(db: Session, storage: ObjectStorage, job: Job, *, commit: Callable[[], None]) -> Job:
    started = time.perf_counter()
    handler = HANDLERS.get(job.type)
    if handler is None:
        jobs.fail(db, job, code="unknown_job_type", message=job.type, retryable=False)
        commit()
        return job
    ctx = JobContext(db=db, storage=storage, job=job, commit=commit)
    try:
        result = handler(ctx)
    except JobWaitingForInputError as exc:
        jobs.wait_for_input(db, job, exc.result)
        commit()
        return job
    except jobs.JobCanceledError as exc:
        log.info("job %s stopped: %s", job.id, exc)
        jobs.cancel(db, job, reason=str(exc))
        commit()
        return job
    except JobFailureError as exc:
        jobs.fail(
            db,
            job,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )
    except Exception as exc:  # a crash must never take the runner down
        log.exception("job %s crashed", job.id)
        jobs.fail(
            db,
            job,
            code="internal_error",
            message=f"{type(exc).__name__}: {exc}",
            retryable=True,
        )
    else:
        jobs.succeed(db, job, result)
    commit()
    log.info(
        "job finished",
        extra={
            "status": job.status.value,
            "attempts": job.attempts,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "cost_usd": str(job.cost_usd),
        },
    )
    return job


def run_once(
    db: Session,
    storage: ObjectStorage,
    *,
    commit: Callable[[], None],
    job_types: frozenset[str] | None = None,
) -> Job | None:
    job = jobs.claim_next(db, job_types)
    if job is None:
        return None
    if job.cancel_requested:  # canceled between enqueue and claim
        jobs.cancel(db, job, reason="canceled before it started")
        commit()
        return job
    commit()  # make the claim visible before the (possibly long) handler runs
    return execute(db, storage, job, commit=commit)


def serve(
    settings: Settings | None = None,
    *,
    poll_interval: float = 1.0,
    stop: threading.Event | None = None,
    storage: ObjectStorage | None = None,
) -> None:
    import app.jobs.handlers  # noqa: F401 — registers handlers

    settings = settings or load_settings()
    observability.configure_logging(settings.log_level, json_output=settings.app_env != "local")
    stop = stop or threading.Event()
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    storage = storage or S3Storage(settings)

    def _shutdown(*_: object) -> None:
        log.info("shutdown requested")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown)

    log.info("job runner started (handlers: %s)", sorted(HANDLERS))
    while not stop.is_set():
        session = factory()
        try:
            for stale in jobs.reap_stale(session):
                log.warning("job %s timed out after %s s", stale.id, stale.timeout_seconds)
            session.commit()
            job = run_once(session, storage, commit=session.commit)
        except Exception:
            log.exception("runner iteration failed")
            session.rollback()
            job = None
        finally:
            session.close()
        if job is None:
            stop.wait(poll_interval)
    engine.dispose()
