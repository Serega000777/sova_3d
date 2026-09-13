"""T-012/T-013: presigned upload session + hash-verified asset registration over HTTP."""

import hashlib
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.models import Asset, UploadSession
from app.models.core import WorkspaceRole
from app.models.uploads import UploadStatus
from app.storage import ObjectNotFoundError, S3Storage
from tests.integration.conftest import Actor, make_actor

STL_ASCII = b"solid cube\n  facet normal 0 0 1\n    outer loop\n" + b"x" * 200 + b"\nendsolid\n"
GLB_LIKE = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 120


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def start_upload(
    api_client: TestClient,
    actor: Actor,
    *,
    filename: str = "cube.stl",
    content_type: str = "model/stl",
    byte_size: int = len(STL_ASCII),
    headers: dict[str, str] | None = None,
) -> Response:
    response: Response = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": filename,
            "content_type": content_type,
            "byte_size": byte_size,
        },
        headers={**actor.headers, **(headers or {})},
    )
    return response


def put_bytes(url: str, data: bytes, content_type: str) -> None:
    response = httpx.put(url, content=data, headers={"Content-Type": content_type})
    assert response.status_code == 200, response.text


def complete(api_client: TestClient, actor: Actor, upload_id: str, digest: str) -> Response:
    response: Response = api_client.post(
        "/api/v1/assets/complete",
        json={"upload_id": upload_id, "sha256": digest, "units": "mm"},
        headers=actor.headers,
    )
    return response


# --- T-012 -----------------------------------------------------------------------------------


def test_create_upload_returns_presigned_put(api_client: TestClient, actor: Actor) -> None:
    response = start_upload(api_client, actor)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["method"] == "PUT" and body["format"] == "stl"
    assert body["headers"] == {"Content-Type": "model/stl"}
    assert body["storage_key"].startswith(f"ws/{actor.workspace.id}/uploads/")
    assert "X-Amz-Signature" in body["url"]
    assert response.headers["X-Request-ID"]


def test_upload_requires_auth_and_membership(api_client: TestClient, db_session: Session) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)

    anonymous = api_client.post("/api/v1/uploads", json={})
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "unauthorized"

    bad_token = start_upload(api_client, owner, headers={"Authorization": "Bearer pai_nope"})
    assert bad_token.status_code == 401

    # A stranger sees "not found", never "forbidden": workspace ids are not probeable.
    foreign = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(owner.workspace.id),
            "filename": "a.stl",
            "content_type": "model/stl",
            "byte_size": 10,
        },
        headers=stranger.headers,
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["details"]["resource"] == "workspace"


def test_viewer_cannot_upload(api_client: TestClient, db_session: Session) -> None:
    viewer = make_actor(db_session, role=WorkspaceRole.viewer)
    response = start_upload(api_client, viewer)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(
    ("filename", "content_type", "byte_size", "status", "code"),
    [
        ("model.exe", "application/octet-stream", 10, 415, "unsupported_format"),
        ("model.stl", "image/png", 10, 415, "unsupported_format"),
        ("model.stl", "model/stl", 200 * 1024 * 1024 + 1, 413, "payload_too_large"),
        ("model.stl", "model/stl", 0, 422, "validation_failed"),
    ],
)
def test_upload_constraints(
    api_client: TestClient,
    actor: Actor,
    filename: str,
    content_type: str,
    byte_size: int,
    status: int,
    code: str,
) -> None:
    response = start_upload(
        api_client, actor, filename=filename, content_type=content_type, byte_size=byte_size
    )
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code and error["trace_id"]


def test_upload_idempotency_key_returns_same_session(api_client: TestClient, actor: Actor) -> None:
    first = start_upload(api_client, actor, headers={"Idempotency-Key": "retry-1"})
    second = start_upload(api_client, actor, headers={"Idempotency-Key": "retry-1"})
    assert first.status_code == second.status_code == 201
    assert first.json()["upload_id"] == second.json()["upload_id"]
    third = start_upload(api_client, actor, headers={"Idempotency-Key": "retry-2"})
    assert third.json()["upload_id"] != first.json()["upload_id"]


# --- T-013 -----------------------------------------------------------------------------------


def test_complete_verifies_hash_and_registers_asset(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    created = start_upload(api_client, actor).json()
    put_bytes(created["url"], STL_ASCII, "model/stl")

    response = complete(api_client, actor, created["upload_id"], sha(STL_ASCII))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sha256"] == sha(STL_ASCII)
    assert body["format"] == "stl" and body["mime"] == "model/stl"
    assert body["byte_size"] == len(STL_ASCII) and body["units"] == "mm"
    assert body["workspace_id"] == str(actor.workspace.id)

    asset = db_session.get(Asset, uuid.UUID(body["id"]))
    assert asset is not None
    assert asset.storage_key == S3Storage.object_key(actor.workspace.id, asset.sha256, "stl")
    assert asset.metadata_ == {"filename": "cube.stl"}
    assert storage.get(asset.storage_key) == STL_ASCII
    with pytest.raises(ObjectNotFoundError):
        storage.head(created["storage_key"])  # staging object is gone

    upload = db_session.get(UploadSession, uuid.UUID(created["upload_id"]))
    assert upload is not None
    assert upload.status is UploadStatus.completed and upload.asset_id == asset.id
    storage.delete(asset.storage_key)


def test_complete_is_idempotent_and_dedupes_by_hash(
    api_client: TestClient, actor: Actor, storage: S3Storage
) -> None:
    first = start_upload(api_client, actor).json()
    put_bytes(first["url"], STL_ASCII, "model/stl")
    asset_a = complete(api_client, actor, first["upload_id"], sha(STL_ASCII)).json()
    retry = complete(api_client, actor, first["upload_id"], sha(STL_ASCII)).json()
    assert retry["id"] == asset_a["id"]

    second = start_upload(api_client, actor, filename="same-bytes.stl").json()
    put_bytes(second["url"], STL_ASCII, "model/stl")
    asset_b = complete(api_client, actor, second["upload_id"], sha(STL_ASCII)).json()
    assert asset_b["id"] == asset_a["id"]
    with pytest.raises(ObjectNotFoundError):
        storage.head(second["storage_key"])
    storage.delete(S3Storage.object_key(actor.workspace.id, asset_a["sha256"], "stl"))


def test_complete_rejects_hash_mismatch(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    created = start_upload(api_client, actor).json()
    put_bytes(created["url"], STL_ASCII, "model/stl")

    response = complete(api_client, actor, created["upload_id"], "0" * 64)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"]["actual"] == sha(STL_ASCII)

    upload = db_session.get(UploadSession, uuid.UUID(created["upload_id"]))
    assert upload is not None and upload.status is UploadStatus.rejected
    assert upload.rejection_reason == "hash_mismatch"
    with pytest.raises(ObjectNotFoundError):
        storage.head(created["storage_key"])
    assert complete(api_client, actor, created["upload_id"], sha(STL_ASCII)).status_code == 409


def test_complete_rejects_size_mismatch(api_client: TestClient, actor: Actor) -> None:
    created = start_upload(api_client, actor, byte_size=len(STL_ASCII) + 5).json()
    # The presigned URL is bound to the declared length, so MinIO refuses the short body...
    short = httpx.put(created["url"], content=STL_ASCII, headers={"Content-Type": "model/stl"})
    assert short.status_code == 403
    # ...and completing without an object is a clear 422, not a 500.
    response = complete(api_client, actor, created["upload_id"], sha(STL_ASCII))
    assert response.status_code == 422
    assert "no object" in response.json()["error"]["message"]


def test_complete_rejects_wrong_magic_bytes(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    created = start_upload(
        api_client,
        actor,
        filename="scene.glb",
        content_type="model/gltf-binary",
        byte_size=len(STL_ASCII),
    ).json()
    put_bytes(created["url"], STL_ASCII, "model/gltf-binary")  # STL bytes in a .glb

    response = complete(api_client, actor, created["upload_id"], sha(STL_ASCII))
    assert response.status_code == 415
    assert response.json()["error"]["details"] == {"declared": "glb", "detected": None}
    upload = db_session.get(UploadSession, uuid.UUID(created["upload_id"]))
    assert upload is not None and upload.rejection_reason == "magic_mismatch"


def test_complete_accepts_matching_magic_bytes(
    api_client: TestClient, actor: Actor, storage: S3Storage
) -> None:
    created = start_upload(
        api_client,
        actor,
        filename="scene.glb",
        content_type="model/gltf-binary",
        byte_size=len(GLB_LIKE),
    ).json()
    put_bytes(created["url"], GLB_LIKE, "model/gltf-binary")
    response = complete(api_client, actor, created["upload_id"], sha(GLB_LIKE))
    assert response.status_code == 201, response.text
    storage.delete(S3Storage.object_key(actor.workspace.id, sha(GLB_LIKE), "glb"))


def test_complete_is_workspace_scoped(api_client: TestClient, db_session: Session) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    created = start_upload(api_client, owner).json()
    response = complete(api_client, stranger, created["upload_id"], sha(STL_ASCII))
    assert response.status_code == 404
