"""MP4 upload -> sandboxed extraction job -> ordinary JPEG photo assets."""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from imageio_ffmpeg import get_ffmpeg_exe
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 - registers extract_video_frames
from app.jobs import runner
from app.models import Asset
from app.models.execution import JobStatus
from app.services.ai_commands import photos_for
from app.storage import S3Storage
from tests.integration.conftest import Actor


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        try:
            storage.delete(key)
        except Exception:
            pass


def make_mp4(
    path: Path,
    *,
    duration: float = 2.0,
    width: int = 320,
    height: int = 240,
    fps: int = 8,
) -> bytes:
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


def upload(
    api_client: TestClient,
    actor: Actor,
    payload: bytes,
    *,
    filename: str = "reference.mp4",
    content_type: str = "video/mp4",
) -> dict[str, object]:
    created = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": filename,
            "content_type": content_type,
            "byte_size": len(payload),
        },
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    put = httpx.put(body["url"], content=payload, headers={"Content-Type": content_type})
    assert put.status_code == 200, put.text
    completed = api_client.post(
        "/api/v1/assets/complete",
        json={"upload_id": body["upload_id"], "sha256": hashlib.sha256(payload).hexdigest()},
        headers=actor.headers,
    )
    assert completed.status_code == 201, completed.text
    return completed.json()


def enqueue(api_client: TestClient, actor: Actor, asset_id: str) -> uuid.UUID:
    response = api_client.post(
        f"/api/v1/assets/{asset_id}/extract-video-frames",
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["job_id"])


def test_valid_mp4_job_creates_four_jpeg_assets(
    tmp_path: Path,
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    source = upload(api_client, actor, make_mp4(tmp_path / "valid.mp4"))
    source_asset = db_session.get(Asset, uuid.UUID(str(source["id"])))
    assert source_asset is not None
    cleanup_keys.append(source_asset.storage_key)

    job_id = enqueue(api_client, actor, str(source["id"]))
    done = runner.run_once(db_session, storage, commit=db_session.flush)

    assert done is not None and done.id == job_id
    assert done.status is JobStatus.succeeded, done.error
    result = done.result or {}
    assert len(result["asset_ids"]) == 4
    assert [frame["timestamp_seconds"] for frame in result["frames"]] == [
        0.25,
        0.75,
        1.25,
        1.75,
    ]
    ids = [uuid.UUID(value) for value in result["asset_ids"]]
    assets = [db_session.get(Asset, asset_id) for asset_id in ids]
    assert all(asset is not None for asset in assets)
    assert all(asset.format == "jpeg" and asset.mime == "image/jpeg" for asset in assets if asset)
    assert all(asset.byte_size < 5 * 1024 * 1024 for asset in assets if asset)
    assert all(
        storage.get(asset.storage_key).startswith(b"\xff\xd8\xff") for asset in assets if asset
    )
    assert photos_for(db_session, workspace_id=actor.workspace.id, asset_ids=ids) == [
        {"asset_id": str(asset_id), "media_type": "image/jpeg"} for asset_id in ids
    ]
    cleanup_keys.extend(asset.storage_key for asset in assets if asset)


@pytest.mark.parametrize(
    ("duration", "width", "height", "message_part"),
    [
        (61.0, 16, 16, "duration"),
        (1.0, 2048, 1152, "resolution"),
    ],
)
def test_video_metadata_limits_fail_job_before_decode(
    tmp_path: Path,
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    duration: float,
    width: int,
    height: int,
    message_part: str,
) -> None:
    payload = make_mp4(
        tmp_path / f"invalid-{message_part}.mp4",
        duration=duration,
        width=width,
        height=height,
        fps=1,
    )
    source = upload(api_client, actor, payload)
    source_asset = db_session.get(Asset, uuid.UUID(str(source["id"])))
    assert source_asset is not None
    cleanup_keys.append(source_asset.storage_key)

    job_id = enqueue(api_client, actor, str(source["id"]))
    done = runner.run_once(db_session, storage, commit=db_session.flush)

    assert done is not None and done.id == job_id
    assert done.status is JobStatus.failed
    assert done.error is not None
    assert done.error["code"] == "input_too_large"
    assert message_part in done.error["message"]


def test_mp4_rejects_wrong_mime_and_magic(
    api_client: TestClient,
    actor: Actor,
) -> None:
    wrong_mime = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": "reference.mp4",
            "content_type": "image/jpeg",
            "byte_size": 16,
        },
        headers=actor.headers,
    )
    assert wrong_mime.status_code == 415
    assert wrong_mime.json()["error"]["code"] == "unsupported_format"

    too_large = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": "reference.mp4",
            "content_type": "video/mp4",
            "byte_size": 48 * 1024 * 1024 + 1,
        },
        headers=actor.headers,
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "payload_too_large"

    payload = b"not an mp4 file"
    created = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": "reference.mp4",
            "content_type": "video/mp4",
            "byte_size": len(payload),
        },
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    put = httpx.put(body["url"], content=payload, headers={"Content-Type": "video/mp4"})
    assert put.status_code == 200, put.text
    completed = api_client.post(
        "/api/v1/assets/complete",
        json={"upload_id": body["upload_id"], "sha256": hashlib.sha256(payload).hexdigest()},
        headers=actor.headers,
    )
    assert completed.status_code == 415
    assert completed.json()["error"]["details"] == {"declared": "mp4", "detected": None}
