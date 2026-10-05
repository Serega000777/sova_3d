"""Self-learning plan step 3: consent-filtered, pseudonymised candidate dataset export."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.execution import AIRequest, AIRequestStatus, Job, JobStatus
from app.models.feedback import AIFeedback, FeedbackRating
from app.models.versioning import ProjectVersion
from app.services.training_dataset import (
    SCHEMA_VERSION,
    build_candidate_dataset,
    export_candidate_dataset,
)
from tests.integration.conftest import Actor

SECRET = b"test-only-training-dataset-secret-32-bytes"


def _create_project(api_client: TestClient, actor: Actor, name: str) -> str:
    response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": name},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _seed_samples(db: Session, actor: Actor, project_id: str) -> tuple[AIRequest, Job]:
    version = ProjectVersion(project_id=uuid.UUID(project_id), sequence_no=1)
    db.add(version)
    db.flush()
    request = AIRequest(
        workspace=actor.workspace,
        project_id=uuid.UUID(project_id),
        prompt=("Send /home/alice/private.stl to owner@example.com or +7 (999) 123-45-67"),
        context={
            "asset_id": str(uuid.uuid4()),
            "source_url": "https://private.example/path",
            "dimensions_mm": [10, 20, 30],
        },
        provider="anthropic",
        model="claude",
        status=AIRequestStatus.executed,
        output_plan={"operation": "scale", "entity_id": str(uuid.uuid4())},
        result_version_id=version.id,
    )
    job = Job(
        workspace=actor.workspace,
        project_id=uuid.UUID(project_id),
        type="reconstruct_scan",
        status=JobStatus.succeeded,
        input={"scan_session_id": str(uuid.uuid4()), "filename": "Alice-room.usdz"},
        result={"version_id": str(version.id), "report_url": "https://private.example/report"},
    )
    db.add_all([request, job])
    db.flush()
    db.add_all(
        [
            AIFeedback(
                project_id=uuid.UUID(project_id),
                ai_request_id=request.id,
                user_id=actor.user.id,
                rating=FeedbackRating.good,
            ),
            AIFeedback(
                project_id=uuid.UUID(project_id),
                job_id=job.id,
                user_id=actor.user.id,
                rating=FeedbackRating.fixed,
            ),
        ]
    )
    db.flush()
    return request, job


def test_dataset_exports_only_currently_consented_projects_and_redacts_identifiers(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    included_id = _create_project(api_client, actor, "Included")
    excluded_id = _create_project(api_client, actor, "Excluded")
    included_request, included_job = _seed_samples(db_session, actor, included_id)
    excluded_request, _ = _seed_samples(db_session, actor, excluded_id)

    consent = api_client.put(
        f"/api/v1/projects/{included_id}/training-consent",
        json={"enabled": True},
        headers=actor.headers,
    )
    assert consent.status_code == 200

    manifest, samples = build_candidate_dataset(
        db_session,
        secret=SECRET,
        generated_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )

    assert manifest == {
        "record_type": "manifest",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-10-05T12:00:00Z",
        "sample_counts": {"ai_request": 1, "reconstruction": 1},
        "privacy": {
            "project_consent": "current_opt_in_only",
            "identifiers": "hmac_sha256",
            "direct_identifier_redaction": True,
            "privacy_review_required": True,
        },
    }
    assert [sample["sample_type"] for sample in samples] == [
        "ai_request",
        "reconstruction",
    ]
    assert samples[0]["feedback"][0]["rating"] == "good"
    assert samples[1]["feedback"][0]["rating"] == "fixed"

    serialized = json.dumps(samples, ensure_ascii=False)
    for raw in (
        included_id,
        excluded_id,
        str(included_request.id),
        str(included_job.id),
        str(excluded_request.id),
        str(actor.user.id),
        "owner@example.com",
        "+7 (999) 123-45-67",
        "/home/alice/private.stl",
        "https://private.example",
        "Alice-room.usdz",
    ):
        assert raw not in serialized
    assert "[EMAIL]" in serialized
    assert "[PHONE]" in serialized
    assert "[PATH]" in serialized
    assert "[REDACTED]" in serialized


def test_revocation_excludes_prior_data_from_future_exports(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor, "Revoked")
    _seed_samples(db_session, actor, project_id)
    path = f"/api/v1/projects/{project_id}/training-consent"

    assert api_client.put(path, json={"enabled": True}, headers=actor.headers).status_code == 200
    assert len(build_candidate_dataset(db_session, secret=SECRET)[1]) == 2

    assert api_client.put(path, json={"enabled": False}, headers=actor.headers).status_code == 200
    manifest, samples = build_candidate_dataset(db_session, secret=SECRET)
    assert samples == []
    assert manifest["sample_counts"] == {"ai_request": 0, "reconstruction": 0}


def test_export_is_jsonl_atomic_private_and_keyed(
    api_client: TestClient, actor: Actor, db_session: Session, tmp_path: Path
) -> None:
    project_id = _create_project(api_client, actor, "Export")
    _seed_samples(db_session, actor, project_id)
    api_client.put(
        f"/api/v1/projects/{project_id}/training-consent",
        json={"enabled": True},
        headers=actor.headers,
    )

    destination = tmp_path / "nested" / "training.jsonl"
    summary = export_candidate_dataset(
        db_session,
        destination=destination,
        secret=SECRET,
        generated_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    rows = [json.loads(line) for line in destination.read_text().splitlines()]

    assert summary.total_samples == 2
    assert rows[0]["record_type"] == "manifest"
    assert all(row["schema_version"] == SCHEMA_VERSION for row in rows)
    assert destination.stat().st_mode & 0o777 == 0o600

    _, different_key_samples = build_candidate_dataset(db_session, secret=b"x" * 32)
    assert rows[1]["sample_key"] != different_key_samples[0]["sample_key"]


def test_dataset_secret_must_be_long_enough(db_session: Session) -> None:
    try:
        build_candidate_dataset(db_session, secret=b"short")
    except ValueError as exc:
        assert "at least 32 bytes" in str(exc)
    else:
        raise AssertionError("short dataset secret must be rejected")
