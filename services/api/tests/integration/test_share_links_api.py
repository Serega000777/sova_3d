"""Reference 62/64: revocable, expiring read-only project share links."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import Units, WorkspaceRole
from app.models.versioning import Asset, AssetKind, AssetRole
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_printing_api import seed_version


def box_stl() -> bytes:
    exported = trimesh.creation.box(extents=(20, 10, 5)).export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


def seed_brep_version(
    db: Session, storage: S3Storage, actor: Actor, payload: bytes
) -> tuple[Asset, str]:
    """A version whose only geometry is exact-CAD source, never a viewer-safe mesh."""
    project = projects.create_project(
        db, user_id=actor.user.id, workspace_id=actor.workspace.id, name="cad-source"
    )
    sha = hashlib.sha256(payload).hexdigest()
    key = S3Storage.object_key(actor.workspace.id, sha, "brep")
    storage.put(key, payload, "application/step")
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=sha,
        storage_key=key,
        mime="application/step",
        format="brep",
        byte_size=len(payload),
        units=Units.mm,
    )
    db.add(asset)
    db.flush()
    projects.create_version(
        db, user_id=actor.user.id, project_id=project.id, assets={AssetRole.source: asset.id}
    )
    return asset, str(project.id)


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def test_owner_creates_lists_and_revokes_a_share_link(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, _, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)

    created = api_client.post(
        f"/api/v1/projects/{project.id}/share-links",
        json={"expires_in_hours": 48},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["token"].startswith("shr_")
    link_id = body["id"]

    listed = api_client.get(f"/api/v1/projects/{project.id}/share-links", headers=actor.headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1 and rows[0]["id"] == link_id and rows[0]["revoked_at"] is None
    assert "token" not in rows[0]

    opened = api_client.get(f"/api/v1/share/{body['token']}")
    assert opened.status_code == 200, opened.text
    shared = opened.json()
    assert shared["project_name"] == project.name
    assert shared["model"]["format"] == "stl"
    assert shared["model"]["download_url"]

    revoked = api_client.delete(
        f"/api/v1/projects/{project.id}/share-links/{link_id}", headers=actor.headers
    )
    assert revoked.status_code == 204

    after_revoke = api_client.get(f"/api/v1/share/{body['token']}")
    assert after_revoke.status_code == 404

    # Revoking twice is a harmless no-op, not an error.
    again = api_client.delete(
        f"/api/v1/projects/{project.id}/share-links/{link_id}", headers=actor.headers
    )
    assert again.status_code == 204


def test_share_link_creation_and_revocation_need_the_workspace_owner(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, _, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    editor = make_actor(db_session, role=WorkspaceRole.editor, workspace=actor.workspace)

    refused = api_client.post(
        f"/api/v1/projects/{project.id}/share-links",
        json={"expires_in_hours": 48},
        headers=editor.headers,
    )
    assert refused.status_code == 403

    created = api_client.post(
        f"/api/v1/projects/{project.id}/share-links",
        json={"expires_in_hours": 48},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    refused_list = api_client.get(
        f"/api/v1/projects/{project.id}/share-links", headers=editor.headers
    )
    assert refused_list.status_code == 403

    refused_revoke = api_client.delete(
        f"/api/v1/projects/{project.id}/share-links/{link_id}", headers=editor.headers
    )
    assert refused_revoke.status_code == 403


def test_share_link_rejects_bad_expiry_foreign_project_and_unknown_token(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, _, asset = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(asset.storage_key)
    stranger = make_actor(db_session)

    too_long = api_client.post(
        f"/api/v1/projects/{project.id}/share-links",
        json={"expires_in_hours": 10_000},
        headers=actor.headers,
    )
    assert too_long.status_code == 422

    foreign = api_client.post(
        f"/api/v1/projects/{project.id}/share-links",
        json={"expires_in_hours": 48},
        headers=stranger.headers,
    )
    assert foreign.status_code == 404

    missing = api_client.get("/api/v1/share/shr_this-token-does-not-exist")
    assert missing.status_code == 404

    malformed = api_client.get("/api/v1/share/not-even-the-right-prefix")
    assert malformed.status_code == 404


def test_share_link_never_exposes_cad_source_only_viewer_mesh(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    """A share link must not become a backdoor to download exact-CAD B-Rep source."""
    step_payload = b"ISO-10303-21;\nEND-ISO-10303-21;\n"
    asset, project_id = seed_brep_version(db_session, storage, actor, step_payload)
    cleanup_keys.append(asset.storage_key)

    created = api_client.post(
        f"/api/v1/projects/{project_id}/share-links",
        json={"expires_in_hours": 24},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    opened = api_client.get(f"/api/v1/share/{created.json()['token']}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["model"] is None
