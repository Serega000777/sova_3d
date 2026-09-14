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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

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


@dataclass(slots=True)
class JobContext:
    db: Session
    storage: ObjectStorage
    job: Job
    commit: Callable[[], None]

    def progress(self, percent: int, stage: str) -> None:
        jobs.set_progress(self.db, self.job, percent, stage)
        self.commit()


class Handler(Protocol):
    def __call__(self, ctx: JobContext) -> dict[str, Any]: ...


HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        HANDLERS[job_type] = handler
        return handler

    return decorator


def execute(db: Session, storage: ObjectStorage, job: Job, *, commit: Callable[[], None]) -> Job:
    """Run the handler for an already-claimed (running) job and persist the outcome."""
    handler = HANDLERS.get(job.type)
    if handler is None:
        jobs.fail(db, job, code="unknown_job_type", message=job.type, retryable=False)
        commit()
        return job
    ctx = JobContext(db=db, storage=storage, job=job, commit=commit)
    try:
        result = handler(ctx)
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
