"""References 90/97: revocable, expiring public integrity-report verification links."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers the export handler
from app.jobs import runner
from app.models.core import WorkspaceRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_printing_api import seed_version


def box_stl() -> bytes:
    exported = trimesh.creation.box(extents=(20, 10, 5)).export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def _run_all(db: Session, storage: S3Storage) -> None:
    while runner.run_once(db, storage, commit=db.flush) is not None:
        pass


def _checked_version(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> tuple[str, list[str]]:
    """A version with a real persisted integrity job, ready to be verification-linked."""
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/exports",
        json={"format": "glb", "printable": False},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    _run_all(db_session, storage)
    return str(version.id), [asset.storage_key]


def test_owner_creates_lists_and_revokes_a_verification_link(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    version_id, keys = _checked_version(api_client, actor, db_session, storage)
    cleanup_keys.extend(keys)

    created = api_client.post(
        f"/api/v1/models/{version_id}/verification-links",
        json={"expires_in_hours": 72},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["token"].startswith("vrf_")
    link_id = body["id"]

    listed = api_client.get(
        f"/api/v1/models/{version_id}/verification-links", headers=actor.headers
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1 and rows[0]["id"] == link_id and rows[0]["revoked_at"] is None
    assert "token" not in rows[0]

    opened = api_client.get(f"/api/v1/verify/{body['token']}")
    assert opened.status_code == 200, opened.text
    verified = opened.json()
    assert verified["version_id"] == version_id
    assert "report" in verified and isinstance(verified["report"], dict)
    assert verified["job_id"]

    revoked = api_client.delete(
        f"/api/v1/models/{version_id}/verification-links/{link_id}", headers=actor.headers
    )
    assert revoked.status_code == 204

    after_revoke = api_client.get(f"/api/v1/verify/{body['token']}")
    assert after_revoke.status_code == 404

    again = api_client.delete(
        f"/api/v1/models/{version_id}/verification-links/{link_id}", headers=actor.headers
    )
    assert again.status_code == 204


def test_verification_link_creation_and_revocation_need_the_workspace_owner(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    version_id, keys = _checked_version(api_client, actor, db_session, storage)
    cleanup_keys.extend(keys)
    editor = make_actor(db_session, role=WorkspaceRole.editor, workspace=actor.workspace)

    refused = api_client.post(
        f"/api/v1/models/{version_id}/verification-links",
        json={"expires_in_hours": 72},
        headers=editor.headers,
    )
    assert refused.status_code == 403

    created = api_client.post(
        f"/api/v1/models/{version_id}/verification-links",
        json={"expires_in_hours": 72},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    assert (
        api_client.get(
            f"/api/v1/models/{version_id}/verification-links", headers=editor.headers
        ).status_code
        == 403
    )
    assert (
        api_client.delete(
            f"/api/v1/models/{version_id}/verification-links/{link_id}", headers=editor.headers
        ).status_code
        == 403
    )


def test_verification_link_rejects_bad_expiry_foreign_version_and_unknown_token(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    version_id, keys = _checked_version(api_client, actor, db_session, storage)
    cleanup_keys.extend(keys)
    stranger = make_actor(db_session)

    too_long = api_client.post(
        f"/api/v1/models/{version_id}/verification-links",
        json={"expires_in_hours": 10_000},
        headers=actor.headers,
    )
    assert too_long.status_code == 422

    foreign = api_client.post(
        f"/api/v1/models/{version_id}/verification-links",
        json={"expires_in_hours": 72},
        headers=stranger.headers,
    )
    assert foreign.status_code == 404

    assert api_client.get("/api/v1/verify/vrf_this-token-does-not-exist").status_code == 404
    assert api_client.get("/api/v1/verify/not-even-the-right-prefix").status_code == 404


def test_verification_link_404s_when_the_version_has_no_checked_report(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    """A link created before any export job exists is honest about having nothing to show."""
    _, version, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)

    created = api_client.post(
        f"/api/v1/models/{version.id}/verification-links",
        json={"expires_in_hours": 24},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    opened = api_client.get(f"/api/v1/verify/{created.json()['token']}")
    assert opened.status_code == 404
