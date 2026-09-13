"""T-011: S3 adapter put/get/head/copy/delete and presigned URLs against MinIO."""

import os
import uuid
from collections.abc import Iterator

import httpx
import pytest
from botocore.exceptions import EndpointConnectionError

from app.config import Settings
from app.storage import ObjectNotFoundError, S3Storage, sha256_hex

DEFAULT_S3 = {
    "S3_ENDPOINT": "http://localhost:19000",
    "S3_BUCKET": "physical-ai-dev",
    "S3_ACCESS_KEY": "physicalai",
    "S3_SECRET_KEY": "physicalai_dev_secret",
}


@pytest.fixture(scope="module")
def storage() -> S3Storage:
    env = {key: os.environ.get(f"TEST_{key}", default) for key, default in DEFAULT_S3.items()}
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://u:p@localhost/x",
            "redis_url": "redis://localhost/0",
            **{key.lower(): value for key, value in env.items()},
        }
    )
    s3 = S3Storage(settings)
    try:
        s3.head("__probe__")
    except ObjectNotFoundError:
        pass
    except EndpointConnectionError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"S3 unreachable at {settings.s3_endpoint}: {exc}")
    return s3


@pytest.fixture
def key(storage: S3Storage) -> Iterator[str]:
    key = f"test/{uuid.uuid4()}.bin"
    yield key
    storage.delete(key)


def test_key_layout_is_workspace_scoped_and_content_addressed() -> None:
    ws = uuid.uuid4()
    sha = "ab" * 32
    assert S3Storage.object_key(ws, sha, ".STL") == f"ws/{ws}/assets/ab/{sha}.stl"
    upload = uuid.uuid4()
    assert S3Storage.upload_key(ws, upload) == f"ws/{ws}/uploads/{upload}"


def test_put_head_get_delete(storage: S3Storage, key: str) -> None:
    payload = b"solid cube\nendsolid cube\n"
    info = storage.put(key, payload, "model/stl")
    assert info.key == key and info.byte_size == len(payload)
    assert info.content_type == "model/stl"
    assert storage.get(key) == payload
    assert storage.head(key).etag == info.etag

    storage.delete(key)
    with pytest.raises(ObjectNotFoundError):
        storage.head(key)
    with pytest.raises(ObjectNotFoundError):
        storage.get(key)


def test_copy_moves_staged_upload_to_content_address(storage: S3Storage, key: str) -> None:
    payload = b"\x00\x01\x02" * 100
    storage.put(key, payload, "application/octet-stream")
    dest = S3Storage.object_key(uuid.uuid4(), sha256_hex(payload), "bin")
    try:
        info = storage.copy(key, dest)
        assert info.byte_size == len(payload)
        assert storage.get(dest) == payload
    finally:
        storage.delete(dest)


def test_copy_missing_source_raises(storage: S3Storage) -> None:
    with pytest.raises(ObjectNotFoundError):
        storage.copy("test/does-not-exist", "test/never-created")


def test_presigned_put_and_get_roundtrip(storage: S3Storage, key: str) -> None:
    payload = b"presigned body"
    put_url = storage.presign_put(key, "text/plain", len(payload), ttl_seconds=60)
    response = httpx.put(put_url, content=payload, headers={"Content-Type": "text/plain"})
    assert response.status_code == 200, response.text

    get_url = storage.presign_get(key, ttl_seconds=60)
    assert httpx.get(get_url).content == payload


def test_presigned_put_rejects_mismatched_content_type(storage: S3Storage, key: str) -> None:
    put_url = storage.presign_put(key, "model/stl", 3, ttl_seconds=60)
    response = httpx.put(put_url, content=b"abc", headers={"Content-Type": "text/plain"})
    assert response.status_code == 403
    with pytest.raises(ObjectNotFoundError):
        storage.head(key)
