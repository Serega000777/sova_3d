"""T-095: a job can be asked to stop, and a job whose worker died does not run forever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.jobs import runner
from app.jobs.runner import JobContext
from app.models.execution import FailureClass, Job, JobStatus
from app.services import jobs
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


@pytest.fixture(autouse=True)
def restore_handlers() -> Any:
    """These tests register throwaway handlers; put the registry back afterwards."""
    saved = dict(runner.HANDLERS)
    yield
    runner.HANDLERS.clear()
    runner.HANDLERS.update(saved)


def enqueue(db: Session, actor: Actor, job_type: str = "test_job") -> Job:
    return jobs.enqueue(
        db,
        workspace_id=actor.workspace.id,
        job_type=job_type,
        input={},
        created_by=actor.user.id,
    )


def test_queued_job_is_canceled_immediately(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    job = enqueue(db_session, actor)
    response = api_client.post(f"/api/v1/jobs/{job.id}/cancel", headers=actor.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "canceled"
    assert body["cancel_requested"] is True
    assert body["error"]["code"] == "canceled"

    # The runner must not pick it up afterwards.
    assert runner.run_once(db_session, storage, commit=db_session.flush) is None


def test_a_running_job_stops_at_its_next_checkpoint(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    stages: list[str] = []

    @runner.register("test_job")
    def handler(ctx: JobContext) -> dict[str, Any]:
        ctx.progress(10, "first")
        stages.append("first")
        # The user hits cancel while the job is working.
        jobs.request_cancel(ctx.db, user_id=actor.user.id, job_id=ctx.job.id)
        ctx.progress(50, "second")  # must not return
        stages.append("second")
        return {"done": True}

    job = enqueue(db_session, actor)
    runner.run_once(db_session, storage, commit=db_session.flush)

    db_session.refresh(job)
    assert stages == ["first"]  # stopped between checkpoints, mid-work state discarded
    assert job.status is JobStatus.canceled
    assert job.result is None
    assert (job.error or {})["code"] == "canceled"


def test_cancelling_a_finished_job_is_a_conflict(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    @runner.register("test_job")
    def handler(ctx: JobContext) -> dict[str, Any]:
        return {"ok": True}

    job = enqueue(db_session, actor)
    runner.run_once(db_session, storage, commit=db_session.flush)
    db_session.refresh(job)
    assert job.status is JobStatus.succeeded

    response = api_client.post(f"/api/v1/jobs/{job.id}/cancel", headers=actor.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_a_job_that_outlives_its_budget_stops_itself(
    actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    @runner.register("test_job")
    def handler(ctx: JobContext) -> dict[str, Any]:
        # Pretend the work started long ago; the next checkpoint must refuse to continue.
        ctx.job.started_at = datetime.now(UTC) - timedelta(hours=2)
        ctx.db.flush()
        ctx.progress(50, "too late")
        return {"done": True}

    job = enqueue(db_session, actor)
    runner.run_once(db_session, storage, commit=db_session.flush)

    db_session.refresh(job)
    assert job.status in (JobStatus.failed, JobStatus.queued)  # retryable: may be requeued
    assert (job.error or {})["code"] == "job_timeout"
    assert job.failure_class is FailureClass.retryable


def test_an_abandoned_running_job_is_reaped(actor: Actor, db_session: Session) -> None:
    """The worker process died: nothing will ever write a terminal state for this job."""
    job = enqueue(db_session, actor, "reconstruct_scan")
    job.status = JobStatus.running
    db_session.flush()
    job.started_at = datetime.now(UTC) - timedelta(seconds=job.timeout_seconds + 60)
    db_session.flush()

    (reaped,) = jobs.reap_stale(db_session)
    assert reaped.id == job.id
    assert (reaped.error or {})["code"] == "job_timeout"
    assert reaped.failure_class is FailureClass.retryable

    # A job still inside its budget is left alone.
    fresh = enqueue(db_session, actor, "reconstruct_scan")
    fresh.status = JobStatus.running
    db_session.flush()
    assert jobs.reap_stale(db_session) == []


def test_a_stranger_cannot_cancel_someone_elses_job(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    job = enqueue(db_session, actor)
    stranger = make_actor(db_session)
    response = api_client.post(f"/api/v1/jobs/{job.id}/cancel", headers=stranger.headers)
    assert response.status_code == 404
    db_session.refresh(job)
    assert job.cancel_requested is False
