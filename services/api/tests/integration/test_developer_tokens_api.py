"""F-066 self-service credentials for the typed public API."""

import uuid

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import hash_token
from app.models.auth import ApiToken
from tests.integration.conftest import Actor, make_actor


def test_developer_token_is_shown_once_works_and_can_be_revoked(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    created = api_client.post(
        "/api/v1/developer-tokens",
        json={"label": "Workshop integration", "expires_in_days": 30},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    secret = body["token"]
    assert secret.startswith("pai_")
    assert body["item"]["label"] == "Workshop integration"
    token_id = body["item"]["id"]

    row = db_session.scalar(sa.select(ApiToken).where(ApiToken.id == uuid.UUID(token_id)))
    assert row is not None
    assert row.token_hash == hash_token(secret)
    assert secret not in row.token_hash
    assert row.label == "developer:Workshop integration"

    listed = api_client.get("/api/v1/developer-tokens", headers=actor.headers)
    assert listed.status_code == 200
    assert listed.json() == [body["item"]]
    assert secret not in listed.text and "token_hash" not in listed.text

    projects = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert projects.status_code == 200

    revoked = api_client.delete(f"/api/v1/developer-tokens/{token_id}", headers=actor.headers)
    assert revoked.status_code == 204
    denied = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert denied.status_code == 401
    assert api_client.get("/api/v1/developer-tokens", headers=actor.headers).json()[0]["revoked_at"]


def test_developer_tokens_are_owner_only_and_bounded(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    token_id = api_client.post(
        "/api/v1/developer-tokens",
        json={"label": "CAD bridge", "expires_in_days": 365},
        headers=actor.headers,
    ).json()["item"]["id"]
    stranger = make_actor(db_session)
    hidden = api_client.delete(f"/api/v1/developer-tokens/{token_id}", headers=stranger.headers)
    assert hidden.status_code == 404
    assert api_client.get("/api/v1/developer-tokens", headers=stranger.headers).json() == []

    too_long = api_client.post(
        "/api/v1/developer-tokens",
        json={"label": "never expires", "expires_in_days": 366},
        headers=actor.headers,
    )
    assert too_long.status_code == 422
    blank = api_client.post(
        "/api/v1/developer-tokens",
        json={"label": "   ", "expires_in_days": 30},
        headers=actor.headers,
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "developer token label must not be empty"
