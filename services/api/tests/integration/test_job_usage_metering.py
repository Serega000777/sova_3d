"""F-068 phase 1: every successful job is shadow-metered exactly once."""

from __future__ import annotations

from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers every production handler
from app.jobs import runner
from app.jobs.runner import JobContext, JobFailureError
from app.models.execution import Job, JobStatus
from app.models.usage import UsageEntry, UsageKind
from app.services import jobs, usage
from app.storage import ObjectStorage
from tests.integration.conftest import Actor

REGISTERED_JOB_TYPES = tuple(sorted(runner.HANDLERS))
NO_STORAGE = cast(ObjectStorage, object())


@pytest.fixture(autouse=True)
def restore_handlers() -> Any:
    saved = dict(runner.HANDLERS)
    yield
    runner.HANDLERS.clear()
    runner.HANDLERS.update(saved)


def enqueue(db: Session, actor: Actor, job_type: str) -> Job:
    return jobs.enqueue(
        db,
        workspace_id=actor.workspace.id,
        job_type=job_type,
        input={},
        created_by=actor.user.id,
    )


@pytest.mark.parametrize("job_type", REGISTERED_JOB_TYPES)
def test_every_registered_job_type_gets_one_shadow_row(
    job_type: str, actor: Actor, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(REGISTERED_JOB_TYPES) >= 30

    def successful(_ctx: JobContext) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setitem(runner.HANDLERS, job_type, successful)
    job = enqueue(db_session, actor, job_type)

    completed = runner.run_once(
        db_session,
        NO_STORAGE,
        commit=db_session.flush,
        job_types=frozenset({job_type}),
    )

    assert completed is job
    assert completed.status is JobStatus.succeeded
    (entry,) = db_session.scalars(sa.select(UsageEntry).where(UsageEntry.job_id == job.id)).all()
    assert entry.idempotency_key == f"job:{job.id}"
    assert entry.kind is UsageKind.credits
    assert entry.quantity == 1 and entry.unit == "job"
    assert entry.cost_usd == 0 and entry.credits_delta == 0
    assert entry.metadata_["action_type"] == job_type
    assert entry.metadata_["metering_mode"] == "shadow"


def test_retry_of_same_job_does_not_double_meter(actor: Actor, db_session: Session) -> None:
    attempts = 0

    @runner.register("retry_meter_test")
    def flaky(ctx: JobContext) -> dict[str, Any]:
        del ctx
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise JobFailureError("temporary", "try again", retryable=True)
        return {"ok": True}

    job = enqueue(db_session, actor, "retry_meter_test")
    runner.run_once(db_session, NO_STORAGE, commit=db_session.flush)
    assert job.status.value == JobStatus.queued.value
    assert (
        db_session.scalar(
            sa.select(sa.func.count()).select_from(UsageEntry).where(UsageEntry.job_id == job.id)
        )
        == 0
    )

    runner.run_once(db_session, NO_STORAGE, commit=db_session.flush)
    usage.record_job_completion(
        db_session,
        job,
        action_type=job.type,
        quantity=1,
        unit="job",
    )

    assert attempts == 2 and job.status.value == JobStatus.succeeded.value
    assert (
        db_session.scalar(
            sa.select(sa.func.count()).select_from(UsageEntry).where(UsageEntry.job_id == job.id)
        )
        == 1
    )


@pytest.mark.parametrize("job_type", ["ai_command", "diagnose_print_photo"])
def test_existing_ai_usage_is_not_duplicated_by_runner(
    job_type: str, actor: Actor, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def provider_metered(ctx: JobContext) -> dict[str, Any]:
        usage.record(
            ctx.db,
            workspace_id=ctx.job.workspace_id,
            kind=UsageKind.ai_tokens,
            quantity=17,
            unit="token",
            job_id=ctx.job.id,
            metadata={"provider": "existing-test-provider", "operation": job_type},
        )
        return {"ok": True}

    monkeypatch.setitem(runner.HANDLERS, job_type, provider_metered)
    job = enqueue(db_session, actor, job_type)
    runner.run_once(db_session, NO_STORAGE, commit=db_session.flush)

    (entry,) = db_session.scalars(sa.select(UsageEntry).where(UsageEntry.job_id == job.id)).all()
    assert entry.idempotency_key is None
    assert entry.kind is UsageKind.ai_tokens and entry.quantity == 17
    assert entry.metadata_["provider"] == "existing-test-provider"


def test_metering_failure_is_fail_open(
    actor: Actor, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    @runner.register("meter_failure_test")
    def successful(ctx: JobContext) -> dict[str, Any]:
        del ctx
        return {"ok": True}

    def fail_meter(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("meter unavailable")

    monkeypatch.setattr(usage, "record_job_completion", fail_meter)
    job = enqueue(db_session, actor, "meter_failure_test")
    runner.run_once(db_session, NO_STORAGE, commit=db_session.flush)

    assert job.status is JobStatus.succeeded and job.result == {"ok": True}
