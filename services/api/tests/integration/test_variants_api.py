"""E24 (F-075): several answers to one request, each a preview; keep one, drop the rest."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def test_three_variants_are_three_previews_and_one_becomes_the_project(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    response = api_client.post(
        f"/api/v1/projects/{project}/variants",
        json={"prompt": "Box 40x20x8 mm", "count": 3},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    variants = response.json()
    assert [v["strategy"] for v in variants] == ["as_described", "rounded", "sturdier"]
    assert variants[1]["title_ru"] == "Со скруглёнными рёбрами"

    jobs = run_all(db_session, storage)
    assert len(jobs) == 3 and all(job.status is JobStatus.succeeded for job in jobs), [
        job.error for job in jobs
    ]
    results = {str(job.input["ai_request_id"]): job.result or {} for job in jobs}
    versions = [results[v["ai_request_id"]] for v in variants]
    assert all(result["preview"] is True for result in versions)
    # the project has no head yet: every answer is a draft
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["head_version"] is None
    # and the answers differ: the rounded one has a fillet, the sturdier one is taller
    types = [[op["type"] for op in result["plan"]["operations"]] for result in versions]
    assert types[0] == ["create_box"]
    assert types[1] == ["create_box", "fillet"]
    assert types[2] == ["create_box", "set_parameter"]

    # keep the rounded one, discard the others
    kept = api_client.post(
        f"/api/v1/versions/{versions[1]['version_id']}/finalize", headers=actor.headers
    )
    assert kept.status_code == 200, kept.text
    for other in (versions[0], versions[2]):
        gone = api_client.delete(f"/api/v1/versions/{other['version_id']}", headers=actor.headers)
        assert gone.status_code == 204, gone.text
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["head_version"]["id"] == versions[1]["version_id"]
    listing = api_client.get(f"/api/v1/projects/{project}/versions", headers=actor.headers)
    assert [v["id"] for v in listing.json()] == [versions[1]["version_id"]]


def test_variant_count_is_bounded(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    too_many = api_client.post(
        f"/api/v1/projects/{project}/variants",
        json={"prompt": "Box 40x20x8 mm", "count": 9},
        headers=actor.headers,
    )
    assert too_many.status_code == 422
