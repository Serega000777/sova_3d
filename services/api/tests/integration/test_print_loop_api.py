"""F-056 end to end: report a print, the profile learns, the next G-code carries it."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Asset
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_calibration_api import default_profile
from tests.integration.test_printing_api import cleanup_keys, run_all, seed_version  # noqa: F401


def test_a_print_report_tunes_the_next_slice_of_that_material(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    profile = default_profile(api_client, actor)
    url = f"/api/v1/printer-profiles/{profile['id']}"
    reported = api_client.post(
        f"{url}/print-reports",
        json={"material_id": "pla", "outcome": "partial", "symptoms": ["stringing", "warping"]},
        headers=actor.headers,
    )
    assert reported.status_code == 200, reported.text
    diagnosis = reported.json()
    assert diagnosis["applied"] and diagnosis["reports"] == 1
    assert diagnosis["tuning"]["retraction_mm"] == 1.7 and diagnosis["tuning"]["brim_mm"] == 5
    assert [f["symptom"] for f in diagnosis["findings"]] == ["stringing", "warping"]

    tuning = api_client.get(f"{url}/tuning", params={"material_id": "pla"}, headers=actor.headers)
    assert tuning.json()["tuning"]["nozzle_offset_c"] == -5
    assert tuning.json()["reports"][0]["symptoms"] == ["stringing", "warping"]
    petg = api_client.get(f"{url}/tuning", params={"material_id": "petg"}, headers=actor.headers)
    assert petg.json()["tuning"] == petg.json()["defaults"]  # PLA's lesson is PLA's

    box = trimesh.creation.box(extents=(20, 10, 4))
    _, version, asset = seed_version(db_session, storage, actor, box.export(file_type="stl"))
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/slice",
        json={"printer_profile_id": profile["id"], "material_id": "pla", "infill_density_pct": 20},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    stats = (job.result or {})["stats"]
    assert stats["tuning"]["retraction_mm"] == 1.7 and stats["brim_loops"] > 0
    gcode_asset = db_session.get(Asset, uuid.UUID((job.result or {})["asset_id"]))
    assert gcode_asset is not None
    cleanup_keys.append(gcode_asset.storage_key)
    link = api_client.get(f"/api/v1/assets/{gcode_asset.id}/download", headers=actor.headers)
    text = httpx.get(link.json()["url"]).text
    assert "G1 E-1.7000" in text and "M104 S195" in text  # PLA 200 - 5
    assert "tuning (learned from print reports)" in text

    reset = api_client.delete(f"{url}/tuning", params={"material_id": "pla"}, headers=actor.headers)
    assert reset.status_code == 200
    after = api_client.get(f"{url}/tuning", params={"material_id": "pla"}, headers=actor.headers)
    assert after.json()["tuning"] == after.json()["defaults"]


def test_only_editors_report_prints(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    from app.models.core import WorkspaceRole

    profile = default_profile(api_client, actor)
    viewer = make_actor(db_session, WorkspaceRole.viewer, workspace=actor.workspace)
    denied = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/print-reports",
        json={"outcome": "failed", "symptoms": ["warping"]},
        headers=viewer.headers,
    )
    assert denied.status_code == 403
    bad = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/print-reports",
        json={"outcome": "failed", "symptoms": ["gremlins"]},
        headers=actor.headers,
    )
    assert bad.status_code == 422


def _jpeg() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_a_photo_of_the_print_adds_what_the_model_sees(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    import sqlalchemy as sa

    from app.ai import print_vision
    from app.ai.contract import Usage
    from app.models.usage import UsageEntry
    from tests.integration.test_imports_api import upload

    profile = default_profile(api_client, actor)
    photo = upload(api_client, actor, _jpeg(), "print.jpg", "image/jpeg")
    url = f"/api/v1/printer-profiles/{profile['id']}/print-photos"
    body = {"material_id": "pla", "outcome": "partial", "symptoms": ["warping"]}
    off = api_client.post(url, json={**body, "photo_asset_ids": [photo]}, headers=actor.headers)
    assert off.status_code == 501 and off.json()["error"]["code"] == "photo_diagnosis_not_enabled"

    settings = api_client.app.state.settings  # type: ignore[attr-defined]
    api_client.app.state.settings = settings.model_copy(update={"ai_provider": "anthropic"})  # type: ignore[attr-defined]
    seen: list[int] = []

    def fake_identify(photos: list[Any], material_id: str, **_: Any) -> Any:
        seen.append(len(photos))
        findings = print_vision.PhotoFindings(
            seen=[print_vision.Seen(symptom="stringing", confidence=0.8, evidence="hairs")]
        )
        spent = Usage(
            provider="anthropic",
            model="claude-opus-5",
            input_tokens=1000,
            output_tokens=100,
            cost_usd=Decimal("0.0075"),
        )
        return findings, spent

    monkeypatch.setattr(print_vision, "client_for", lambda _settings: None)
    monkeypatch.setattr(print_vision, "identify", fake_identify)
    try:
        accepted = api_client.post(
            url, json={**body, "photo_asset_ids": [photo]}, headers=actor.headers
        )
        assert accepted.status_code == 202, accepted.text
        (job,) = run_all(db_session, storage)
    finally:
        api_client.app.state.settings = settings  # type: ignore[attr-defined]
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert seen == [1]
    assert [f["symptom"] for f in result["findings"]] == ["warping", "stringing"]
    assert result["tuning"]["retraction_mm"] == 1.7 and result["tuning"]["brim_mm"] == 5
    assert result["photo"]["seen"][0]["evidence"] == "hairs"
    spent = db_session.scalars(sa.select(UsageEntry).where(UsageEntry.job_id == job.id)).all()
    assert len(spent) == 1 and spent[0].metadata_["operation"] == "diagnose_print_photo"
