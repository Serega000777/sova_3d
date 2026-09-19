"""E26 (F-019): a photo goes in with the command; the model that comes out says how it was sized."""

from __future__ import annotations

import struct
import zlib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import box_bytes, project, run_all, upload  # noqa: F401


def png_bytes(width: int = 4, height: int = 4) -> bytes:
    """A real PNG (grey square) without Pillow: signature + IHDR + IDAT + IEND."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes([128, 128, 128]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_a_photo_command_asks_answers_and_builds_with_a_scale_claim(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    photo_id = upload(api_client, actor, png_bytes(), "stand.png", "image/png")
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={
            "prompt": "Смоделируй предмет с фото",
            "units": "mm",
            "target": "print",
            "image_asset_ids": [photo_id],
            "reference": "карта 85.6 мм",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    (job,) = run_all(db_session, storage)
    # the offline planner cannot see: it asks for the size instead of guessing (T-139)
    assert job.status is JobStatus.waiting_input, job.error
    request = api_client.get(
        f"/api/v1/ai-requests/{accepted['ai_request_id']}", headers=actor.headers
    ).json()
    assert request["status"] == "needs_clarification"
    assert "не видит фото" in request["clarifications"][0]
    assert request["photo_asset_ids"] == [photo_id]

    answered = api_client.post(
        f"/api/v1/ai-requests/{accepted['ai_request_id']}/clarify",
        json={"answers": ["подставка 80×60×40 мм"]},
        headers=actor.headers,
    )
    assert answered.status_code == 202, answered.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["scale"] == {"source": "user", "confidence": "high", "basis": "размеры из текста"}

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    photo = version["provenance"]["photo"]
    assert photo["asset_ids"] == [photo_id] and photo["reference"] == "карта 85.6 мм"
    assert photo["scale"]["source"] == "user"
    assert any("не измерялись" in a for a in version["provenance"]["assumptions"])

    history = api_client.get(
        f"/api/v1/projects/{project}/ai-requests", headers=actor.headers
    ).json()
    assert history[0]["photo_asset_ids"] == [photo_id]


def test_only_this_workspaces_images_can_be_attached(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    stl_id = upload(api_client, actor, box_bytes("stl"), "part.stl", "model/stl")
    refused = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={
            "prompt": "как на фото",
            "units": "mm",
            "target": "print",
            "image_asset_ids": [stl_id],
        },
        headers=actor.headers,
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"

    stranger = make_actor(db_session)
    theirs = upload(api_client, stranger, png_bytes(), "theirs.png", "image/png")
    missing = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={
            "prompt": "как на фото",
            "units": "mm",
            "target": "print",
            "image_asset_ids": [theirs],
        },
        headers=actor.headers,
    )
    assert missing.status_code == 404

    too_many = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={
            "prompt": "как на фото",
            "units": "mm",
            "target": "print",
            "image_asset_ids": [
                upload(api_client, actor, png_bytes(n, n), f"p{n}.png", "image/png")
                for n in range(5, 10)
            ],
        },
        headers=actor.headers,
    )
    assert too_many.status_code == 422
