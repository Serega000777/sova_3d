"""T-011: S3 adapter put/get/head/copy/delete and presigned URLs against MinIO."""

import uuid
from collections.abc import Iterator
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, Literal, cast

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.jobs.artifacts import (
    cleanup_unreferenced_objects,
    lock_derived_asset_objects,
    store_derived_asset,
)
from app.jobs.print_jobs import _store_stl
from app.jobs.runner import JobContext
from app.models.core import Units, User, Workspace, WorkspaceKind
from app.models.versioning import Asset, AssetKind
from app.services.asset_copies import copy_asset_to_workspace
from app.storage import ObjectNotFoundError, S3Storage, sha256_hex


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


@pytest.mark.parametrize("alternate_writer", ["asset_copy", "print_stl"])
def test_rollback_cleanup_holds_content_lock_against_alternate_writer(
    migrated_db: Engine,
    storage: S3Storage,
    alternate_writer: Literal["asset_copy", "print_stl"],
) -> None:
    payload = f"concurrent-{uuid.uuid4()}".encode()
    digest = sha256_hex(payload)
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    source_workspace_id: uuid.UUID
    source_asset_id: uuid.UUID
    job_source_asset_id: uuid.UUID
    with Session(migrated_db) as setup:
        user = User(email=f"content-lock-{uuid.uuid4()}@example.test")
        setup.add(user)
        setup.flush()
        source_workspace = Workspace(
            name="content lock source",
            kind=WorkspaceKind.personal,
            owner_user_id=user.id,
        )
        workspace = Workspace(
            name="content lock proof",
            kind=WorkspaceKind.personal,
            owner_user_id=user.id,
        )
        setup.add_all((source_workspace, workspace))
        setup.flush()
        source_key = storage.object_key(source_workspace.id, digest, "stl")
        storage.put(source_key, payload, "model/stl")
        source_asset = Asset(
            workspace_id=source_workspace.id,
            kind=AssetKind.derived,
            sha256=digest,
            storage_key=source_key,
            mime="model/stl",
            format="stl",
            byte_size=len(payload),
            units=Units.mm,
            metadata_={"test": "copy-source"},
            created_by=user.id,
        )
        job_source_payload = f"job-source-{uuid.uuid4()}".encode()
        job_source_digest = sha256_hex(job_source_payload)
        job_source_key = storage.object_key(workspace.id, job_source_digest, "stl")
        storage.put(job_source_key, job_source_payload, "model/stl")
        job_source_asset = Asset(
            workspace_id=workspace.id,
            kind=AssetKind.original,
            sha256=job_source_digest,
            storage_key=job_source_key,
            mime="model/stl",
            format="stl",
            byte_size=len(job_source_payload),
            units=Units.mm,
            metadata_={"test": "print-job-source"},
            created_by=user.id,
        )
        setup.add_all((source_asset, job_source_asset))
        setup.commit()
        user_id, workspace_id = user.id, workspace.id
        source_workspace_id, source_asset_id = source_workspace.id, source_asset.id
        job_source_asset_id = job_source_asset.id

    key = storage.object_key(workspace_id, digest, "stl")
    attempting = Event()
    stored = Event()
    allow_commit = Event()
    errors: list[BaseException] = []

    def context(session: Session) -> JobContext:
        job = cast(Any, SimpleNamespace(id=uuid.uuid4(), created_by=None))
        return JobContext(db=session, storage=storage, job=job, commit=session.flush)

    def concurrent_writer() -> None:
        try:
            with Session(migrated_db) as second:
                selected_source_id = (
                    source_asset_id if alternate_writer == "asset_copy" else job_source_asset_id
                )
                source_asset = second.get(Asset, selected_source_id)
                assert source_asset is not None
                attempting.set()
                if alternate_writer == "asset_copy":
                    copy_asset_to_workspace(
                        second,
                        storage,
                        source_asset,
                        workspace_id=workspace_id,
                        created_by=user_id,
                    )
                else:
                    _store_stl(context(second), source_asset, payload, "top")
                stored.set()
                if not allow_commit.wait(30):
                    raise TimeoutError("test did not release concurrent commit")
                second.commit()
        except BaseException as exc:  # surfaced in the main test thread below
            errors.append(exc)
            stored.set()

    first = Session(migrated_db)
    thread = Thread(target=concurrent_writer, daemon=True)
    try:
        first_ctx = context(first)
        lock_derived_asset_objects(first_ctx, workspace_id=workspace_id, payloads=(payload,))
        created_keys: set[str] = set()
        with pytest.raises(RuntimeError, match="rollback probe"):
            with first.begin_nested():
                store_derived_asset(
                    first_ctx,
                    workspace_id=workspace_id,
                    data=payload,
                    format_id="stl",
                    metadata={"test": "rollback"},
                    created_by=None,
                    created_object_keys=created_keys,
                )
                raise RuntimeError("rollback probe")

        thread.start()
        assert attempting.wait(5)
        assert not stored.wait(0.5), "alternate writer bypassed the outer advisory lock"
        cleanup_unreferenced_objects(first_ctx, created_keys)
        with pytest.raises(ObjectNotFoundError):
            storage.head(key)
        assert not stored.is_set(), "content lock was released before cleanup completed"
        first.commit()

        assert stored.wait(30)
        allow_commit.set()
        thread.join(30)
        assert not thread.is_alive()
        assert errors == []
        with Session(migrated_db) as verify:
            asset = verify.scalar(
                sa.select(Asset).where(
                    Asset.workspace_id == workspace_id,
                    Asset.sha256 == digest,
                )
            )
            assert asset is not None and asset.storage_key == key
        assert storage.get(key) == payload
    finally:
        allow_commit.set()
        first.rollback()
        first.close()
        if thread.is_alive():
            thread.join(30)
        with Session(migrated_db) as cleanup:
            cleanup.execute(sa.delete(Asset).where(Asset.workspace_id == workspace_id))
            cleanup.execute(sa.delete(Asset).where(Asset.workspace_id == source_workspace_id))
            cleanup.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
            cleanup.execute(sa.delete(Workspace).where(Workspace.id == source_workspace_id))
            cleanup.execute(sa.delete(User).where(User.id == user_id))
            cleanup.commit()
        storage.delete(key)
        storage.delete(source_key)
        storage.delete(job_source_key)


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


@pytest.mark.skip(
    reason="adobe/s3mock (the dev/CI S3 double since MinIO's own images stopped being freely "
    "distributable in 2025) accepts presigned URLs without validating their SigV4 signature "
    "or bound headers by design, so a mismatched Content-Type isn't refused here. The API's "
    "presign_put call and the invariant itself are unchanged; this needs real S3 or MinIO "
    "to exercise."
)
def test_presigned_put_rejects_mismatched_content_type(storage: S3Storage, key: str) -> None:
    put_url = storage.presign_put(key, "model/stl", 3, ttl_seconds=60)
    response = httpx.put(put_url, content=b"abc", headers={"Content-Type": "text/plain"})
    assert response.status_code == 403
    with pytest.raises(ObjectNotFoundError):
        storage.head(key)
