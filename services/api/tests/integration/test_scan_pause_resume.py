"""T-250: real checkpoint-based pause/resume for the reconstruction job pipeline.

The reconstruction job (`handle_reconstruct`) offers exactly one pausable checkpoint,
right after a non-exterior provider's reconstruction call succeeds: the raw mesh is
saved as a durable asset first, so a resume can skip straight to repair/decimate/
texture instead of redoing the (potentially slow) reconstruction. Exterior (COLMAP)
jobs do not get this — their texture-projection context is not persisted in this
increment — which these tests hold the handler to honestly: no skip-ahead claim where
one cannot actually be delivered, and no pause request accepted that would otherwise
sit unconsumed while the job quietly runs to completion anyway.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import reconstruction

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.api.errors import ConflictError
from app.models.execution import JobStatus
from app.services import jobs, scanning
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_scanning_api import (  # noqa: F401 — frame_assets is a fixture
    add_frames,
    frame_assets,
    run_all,
    start_scan,
)


def test_pausing_right_after_reconstruction_lets_resume_skip_it(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_reconstruct = reconstruction.StubReconstructor.reconstruct

    def counted(self: Any, scan_input: Any, out_dir: Any) -> reconstruction.Reconstruction:
        calls["n"] += 1
        return real_reconstruct(self, scan_input, out_dir)

    monkeypatch.setattr(reconstruction.StubReconstructor, "reconstruct", counted)

    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor, label="mug")
    add_frames(api_client, actor, scan["id"], assets, quality={"sharpness": 0.8})
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    job_id = uuid.UUID(accepted.json()["job_id"])

    # The user hits pause right as the (fake, fast) reconstruction call returns — the
    # same checkpoint timing cancellation already relies on elsewhere in this codebase.
    original_for = reconstruction.reconstructor_for

    def pause_after_reconstructing(provider: str) -> reconstruction.Reconstructor:
        real = original_for(provider)
        real_call = real.reconstruct

        def wrapped(scan_input: Any, out_dir: Any) -> reconstruction.Reconstruction:
            result = real_call(scan_input, out_dir)
            jobs.request_pause(db_session, user_id=actor.user.id, job_id=job_id)
            return result

        real.reconstruct = wrapped  # type: ignore[assignment]
        return real

    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.reconstruction.reconstructor_for",
        pause_after_reconstructing,
    )

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.paused
    assert job.pause_requested is False
    assert job.checkpoint is not None
    assert job.checkpoint["stage"] == "reconstructed"
    assert uuid.UUID(job.checkpoint["raw_mesh_asset_id"])
    assert calls["n"] == 1

    paused_scan = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert paused_scan["status"] == "paused"

    resumed = api_client.post(f"/api/v1/scans/{scan['id']}/resume", headers=actor.headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "reconstructing"

    (job_after_resume,) = run_all(db_session, storage)
    assert job_after_resume.status is JobStatus.succeeded, job_after_resume.error
    assert calls["n"] == 1  # the resumed run never called the real reconstructor again

    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    assert ready["report"]["provider"] == "stub"


def test_pausing_a_queued_scan_pauses_the_session_immediately(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,  # noqa: F811
) -> None:
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text

    paused = api_client.post(f"/api/v1/scans/{scan['id']}/pause", headers=actor.headers)
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"

    # The runner must not pick up the now-paused job.
    assert run_all(db_session, storage) == []


def test_exterior_jobs_reject_pause_once_running(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Honest limitation: the exterior branch only calls the plain, non-pausable
    progress() (see the handler's module docstring) — it has no checkpoint to offer.
    Rather than silently accepting a pause request it can never actually honour (which
    would leave `pause_requested` stuck true on a job that finishes anyway),
    `scanning.pause()` rejects the request up front with a clear 409 once the job is
    already running."""
    job_id_box: dict[str, uuid.UUID] = {}
    scan_id_box: dict[str, uuid.UUID] = {}
    rejection_box: dict[str, ConflictError] = {}

    def fake_colmap(
        _self: Any, scan_input: reconstruction.ScanInput, out_dir: Any
    ) -> reconstruction.Reconstruction:
        import trimesh

        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "exterior.ply"
        trimesh.creation.box(extents=(12_000, 7_000, 4_000)).export(mesh_path)
        try:
            scanning.pause(db_session, user_id=actor.user.id, session_id=scan_id_box["id"])
        except ConflictError as exc:
            rejection_box["error"] = exc
        return reconstruction.Reconstruction(
            mesh_path=mesh_path,
            provider="colmap_exterior",
            scale=reconstruction.ScaleReport(12_000, "measured_max_dimension", 0.8),
            coverage=1.0,
            details={"frames": len(scan_input.frames), "placeholder": False},
            format="ply",
            texture_context_path=None,
        )

    monkeypatch.setattr(reconstruction.ColmapExteriorReconstructor, "reconstruct", fake_colmap)
    assets = frame_assets(actor.workspace.id, 32)
    scan = start_scan(
        api_client,
        actor,
        label="building exterior",
        capabilities={"subject": "exterior", "metric_scale": "none"},
    )
    scan_id_box["id"] = uuid.UUID(scan["id"])
    sections = ("front", "right", "back", "left")
    for index, asset in enumerate(assets):
        response = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": str(asset.id),
                "sequence_no": index,
                "pose": {"azimuth_deg": index * 5, "exterior_section": sections[index // 8]},
            },
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": 12_000, "scale_confidence": 0.8},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job_id_box["id"] = uuid.UUID(accepted.json()["job_id"])

    # texture_context_path=None means the handler's own texture_projection_failed path
    # would fire before reaching the end — expected and fine, this test is only about
    # whether the mid-run pause request was rejected, not about a successful finish.
    (job,) = run_all(db_session, storage)
    db_session.refresh(job)
    assert job.status in (JobStatus.failed, JobStatus.succeeded)
    assert "error" in rejection_box  # scanning.pause() rejected it, not silently accepted
    assert job.pause_requested is False  # the request never reached request_pause() at all
    assert job.checkpoint is None


def test_resume_fails_closed_when_the_checkpointed_asset_is_gone(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adversarial: a paused job's checkpoint references a durable asset. If that asset
    is somehow gone by the time it resumes, the handler must fail closed with a clear
    code — never fabricate a mesh or silently fall back to an empty one."""
    original_for = reconstruction.reconstructor_for

    def pause_after_reconstructing(provider: str) -> reconstruction.Reconstructor:
        real = original_for(provider)
        real_call = real.reconstruct

        def wrapped(scan_input: Any, out_dir: Any) -> reconstruction.Reconstruction:
            result = real_call(scan_input, out_dir)
            jobs.request_pause(db_session, user_id=actor.user.id, job_id=job_id)
            return result

        real.reconstruct = wrapped  # type: ignore[assignment]
        return real

    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.reconstruction.reconstructor_for",
        pause_after_reconstructing,
    )

    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    job_id = uuid.UUID(accepted.json()["job_id"])

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.paused
    checkpoint = job.checkpoint
    assert checkpoint is not None
    raw_asset_id = uuid.UUID(checkpoint["raw_mesh_asset_id"])

    from app.models.versioning import Asset

    raw_asset = db_session.get(Asset, raw_asset_id)
    assert raw_asset is not None
    storage.delete(raw_asset.storage_key)

    api_client.post(f"/api/v1/scans/{scan['id']}/resume", headers=actor.headers)
    # checkpoint_asset_missing is marked retryable (same convention as frame_missing
    # above it), so the runner exhausts the job's normal retry budget before giving up —
    # every attempt in that budget must fail the same honest way, never fabricate a mesh.
    attempts = run_all(db_session, storage)
    assert len(attempts) >= 1
    assert all((a.error or {}).get("code") == "checkpoint_asset_missing" for a in attempts)
    job_after_resume = attempts[-1]
    assert job_after_resume.status is JobStatus.failed
    assert job_after_resume.error is not None
    assert job_after_resume.error["code"] == "checkpoint_asset_missing"


def test_pausing_or_resuming_the_wrong_scan_state_is_a_conflict(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,  # noqa: F811
) -> None:
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)

    # Capturing (not reconstructing yet): pause is a conflict.
    not_reconstructing = api_client.post(f"/api/v1/scans/{scan['id']}/pause", headers=actor.headers)
    assert not_reconstructing.status_code == 409

    # Resuming a scan that was never paused is a conflict too.
    not_paused = api_client.post(f"/api/v1/scans/{scan['id']}/resume", headers=actor.headers)
    assert not_paused.status_code == 409

    add_frames(api_client, actor, scan["id"], assets)
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded

    # Ready (terminal from the session's point of view): pause is a conflict.
    already_done = api_client.post(f"/api/v1/scans/{scan['id']}/pause", headers=actor.headers)
    assert already_done.status_code == 409
