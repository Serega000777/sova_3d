"""Self-learning plan step 2: explicit good/bad/fixed feedback on an AI or reconstruction result."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import WorkspaceRole
from app.models.execution import AIRequest, Job
from app.models.versioning import ProjectVersion
from tests.integration.conftest import Actor, make_actor


def _create_project(api_client: TestClient, actor: Actor) -> str:
    response = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Figurine"},
        headers=actor.headers,
    )
    return str(response.json()["id"])


def _ai_request(db: Session, actor: Actor, project_id: str) -> AIRequest:
    request = AIRequest(
        workspace=actor.workspace,
        project_id=uuid.UUID(project_id),
        prompt="a small dragon",
        provider="anthropic",
        model="claude",
    )
    db.add(request)
    db.flush()
    return request


def _job(db: Session, actor: Actor, project_id: str) -> Job:
    job = Job(workspace=actor.workspace, project_id=uuid.UUID(project_id), type="reconstruct")
    db.add(job)
    db.flush()
    return job


def _version(db: Session, project_id: str, sequence_no: int = 1) -> ProjectVersion:
    version = ProjectVersion(project_id=uuid.UUID(project_id), sequence_no=sequence_no)
    db.add(version)
    db.flush()
    return version


def test_feedback_roundtrip_good_bad_fixed(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor)
    request = _ai_request(db_session, actor, project_id)
    job = _job(db_session, actor, project_id)
    version = _version(db_session, project_id)
    path = f"/api/v1/projects/{project_id}/feedback"

    good = api_client.post(
        path, json={"rating": "good", "ai_request_id": str(request.id)}, headers=actor.headers
    )
    assert good.status_code == 201, good.text
    assert good.json()["rating"] == "good"
    assert good.json()["ai_request_id"] == str(request.id)
    assert good.json()["user_id"] == str(actor.user.id)

    fixed = api_client.post(
        path, json={"rating": "fixed", "version_id": str(version.id)}, headers=actor.headers
    )
    assert fixed.status_code == 201
    assert fixed.json()["version_id"] == str(version.id)

    bad = api_client.post(
        path,
        json={"rating": "bad", "reason": "broken_geometry", "job_id": str(job.id)},
        headers=actor.headers,
    )
    assert bad.status_code == 201
    assert bad.json()["reason"] == "broken_geometry"


def test_feedback_requires_reason_only_for_bad(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor)
    request = _ai_request(db_session, actor, project_id)
    path = f"/api/v1/projects/{project_id}/feedback"

    # "bad" without a reason is rejected — the short list exists so it is always filled in
    missing_reason = api_client.post(
        path, json={"rating": "bad", "ai_request_id": str(request.id)}, headers=actor.headers
    )
    assert missing_reason.status_code == 422

    # a reason on a non-"bad" rating is rejected too — it would be meaningless
    stray_reason = api_client.post(
        path,
        json={
            "rating": "good",
            "reason": "other",
            "ai_request_id": str(request.id),
        },
        headers=actor.headers,
    )
    assert stray_reason.status_code == 422

    # no target at all is rejected by the request schema itself
    no_target = api_client.post(path, json={"rating": "good"}, headers=actor.headers)
    assert no_target.status_code == 422


def test_feedback_target_must_belong_to_the_project(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor)
    foreign = make_actor(db_session)
    foreign_project_id = _create_project(api_client, foreign)
    foreign_request = _ai_request(db_session, foreign, foreign_project_id)

    cross = api_client.post(
        f"/api/v1/projects/{project_id}/feedback",
        json={"rating": "good", "ai_request_id": str(foreign_request.id)},
        headers=actor.headers,
    )
    assert cross.status_code == 404


def test_feedback_listing_filters_and_viewer_access(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = _create_project(api_client, actor)
    request = _ai_request(db_session, actor, project_id)
    other_request = _ai_request(db_session, actor, project_id)
    path = f"/api/v1/projects/{project_id}/feedback"

    api_client.post(
        path, json={"rating": "good", "ai_request_id": str(request.id)}, headers=actor.headers
    )
    api_client.post(
        path,
        json={"rating": "good", "ai_request_id": str(other_request.id)},
        headers=actor.headers,
    )

    all_feedback = api_client.get(path, headers=actor.headers)
    assert all_feedback.status_code == 200
    assert len(all_feedback.json()) == 2

    filtered = api_client.get(
        path, params={"ai_request_id": str(request.id)}, headers=actor.headers
    )
    assert [f["ai_request_id"] for f in filtered.json()] == [str(request.id)]

    # a viewer gives feedback too — it is a quality signal, not a project setting
    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    as_viewer = api_client.post(
        path, json={"rating": "fixed", "ai_request_id": str(request.id)}, headers=viewer.headers
    )
    assert as_viewer.status_code == 201
    assert as_viewer.json()["user_id"] == str(viewer.user.id)

    # a stranger cannot see or rate a project they are not a member of
    foreign = make_actor(db_session)
    assert api_client.get(path, headers=foreign.headers).status_code == 404
    assert (
        api_client.post(
            path,
            json={"rating": "good", "ai_request_id": str(request.id)},
            headers=foreign.headers,
        ).status_code
        == 404
    )
