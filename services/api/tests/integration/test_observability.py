"""T-096 one trace id from request to job; T-097 metrics that come from the real tables."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import observability
from app.api.deps import get_db
from app.main import create_app
from app.models.execution import Job
from app.services import jobs
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.conftest import test_s3_settings as make_settings


def test_the_trace_id_reaches_the_job_the_request_queued(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    trace = "11111111-2222-3333-4444-555555555555"
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "traced"},
        headers=actor.headers,
    ).json()["id"]

    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Box 10x10x10 mm"},
        headers={**actor.headers, "X-Request-ID": trace},
    )
    assert response.status_code == 202, response.text
    assert response.headers["x-request-id"] == trace

    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.trace_id == trace  # the same id identifies the work the click caused


def test_a_generated_trace_id_comes_back_on_every_response(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/formats")
    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) >= 32


def test_logs_are_one_json_object_per_line_carrying_the_context(
    caplog: Any,
) -> None:
    formatter = observability.JsonFormatter()
    record = logging.LogRecord(
        name="app.jobs",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job finished",
        args=(),
        exc_info=None,
    )
    record.status = "succeeded"
    with observability.bind(trace_id="abc", job_id="job-1"):
        payload = json.loads(formatter.format(record))
    assert payload["message"] == "job finished"
    assert payload["trace_id"] == "abc" and payload["job_id"] == "job-1"
    assert payload["status"] == "succeeded"
    assert payload["level"] == "INFO"
    # Context does not leak out of the block.
    assert "trace_id" not in json.loads(formatter.format(record))


# --- T-097 -----------------------------------------------------------------------------------


def metrics_client(
    database_url: str, storage: S3Storage, db_session: Session, token: str | None
) -> TestClient:
    """Like the shared api_client, but with a metrics token and the test's own session."""
    settings = make_settings(database_url)
    settings.metrics_token = token
    app = create_app(settings, storage=storage)

    def _override_db() -> Iterator[Session]:
        with db_session.begin_nested():
            yield db_session

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_metrics_are_off_without_a_token(
    database_url: str, storage: S3Storage, db_session: Session
) -> None:
    with metrics_client(database_url, storage, db_session, None) as client:
        assert client.get("/api/v1/metrics").status_code == 404


def test_metrics_need_the_token_and_report_the_real_tables(
    database_url: str, storage: S3Storage, actor: Actor, db_session: Session
) -> None:
    jobs.enqueue(
        db_session,
        workspace_id=actor.workspace.id,
        job_type="export",
        input={},
        created_by=actor.user.id,
    )
    with metrics_client(database_url, storage, db_session, "scrape-me") as client:
        assert client.get("/api/v1/metrics").status_code == 401
        assert (
            client.get("/api/v1/metrics", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        response = client.get("/api/v1/metrics", headers={"Authorization": "Bearer scrape-me"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'physicalai_jobs{status="queued",type="export"}' in body
    assert 'physicalai_jobs_in_flight{type="export"}' in body
    for family in (
        "physicalai_job_duration_seconds",
        "physicalai_job_failures",
        "physicalai_ai_cost_usd",
        "physicalai_geometry_operations",
        "physicalai_scans",
    ):
        assert f"# TYPE {family}" in body or f"# HELP {family}" in body
