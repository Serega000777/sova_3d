"""E31 (F-082): a dedicated 3D scanner streams metric fragments; they fuse into a model."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session
from worker.importers.usdz import write_usdz
from worker.reconstruction import Reconstruction, ScaleReport, ScanInput

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import Job, JobStatus
from app.models.versioning import AssetRole, ProjectVersion, VersionAsset
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import run_all, upload

DEVICE = {
    "device": {
        "kind": "scanner",
        "vendor": "Simulated",
        "model": "Turntable 1",
        "driver": "simulated",
        "accuracy_mm": 0.05,
    }
}


def stl(mesh: trimesh.Trimesh) -> bytes:
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else str(exported).encode()


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (110, 90, 70)).save(buffer, format="JPEG")
    return buffer.getvalue()


def start_scanner_session(api_client: TestClient, actor: Actor, **extra: Any) -> dict[str, Any]:
    response = api_client.post(
        "/api/v1/scans",
        json={
            "workspace_id": str(actor.workspace.id),
            "mode": "scanner",
            "label": "bracket on the turntable",
            "capabilities": DEVICE,
            **extra,
        },
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    session: dict[str, Any] = response.json()
    return session


def test_scanner_fragments_fuse_into_a_metric_model(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "scanner"},
        headers=actor.headers,
    ).json()["id"]
    scan = start_scanner_session(api_client, actor, project_id=project_id)
    assert scan["mode"] == "scanner" and scan["capabilities"]["device"]["vendor"] == "Simulated"

    # two overlapping halves of an 80 x 40 x 20 bracket, as the scanner software delivers them
    left = trimesh.creation.box(extents=(44, 40, 20))
    left.apply_translation((22, 20, 10))
    right = trimesh.creation.box(extents=(44, 40, 20))
    right.apply_translation((58, 20, 10))
    for index, half in enumerate((left, right)):
        asset_id = upload(api_client, actor, stl(half), f"fragment_{index}.stl", "model/stl")
        added = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": asset_id,
                "sequence_no": index,
                "kind": "mesh",
                "pose": {"matrix": np.eye(4).tolist()},
                "quality": {"points": 12000},
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text
    stats = api_client.patch(
        f"/api/v1/scans/{scan['id']}/capture-stats",
        json={"stats": {"fragments": 2, "coverage": 1.0}},
        headers=actor.headers,
    )
    assert stats.status_code == 200 and stats.json()["frame_count"] == 2

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    report = ready["report"]
    assert report["provider"] == "fusion" and report["fusion"] == "union"
    assert report["scale"]["source"] == "device" and report["scale"]["confidence"] >= 0.95
    assert report["scale"]["applied_mm"] == 80.0

    kept = api_client.post(
        f"/api/v1/scans/{scan['id']}/accept",
        json={"label": "Scanned bracket"},
        headers=actor.headers,
    )
    assert kept.status_code == 200, kept.text
    version = db_session.get(ProjectVersion, uuid.UUID(kept.json()["result_version_id"]))
    assert version is not None and version.label == "Scanned bracket"
    assert version.provenance["operation"] == "scan" and version.provenance["mode"] == "scanner"
    assert version.provenance["report"]["scale"]["source"] == "device"


def test_rgb_scan_builds_three_isolated_candidates_and_selects_one(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = api_client.post(
        "/api/v1/scans",
        json={
            "workspace_id": str(actor.workspace.id),
            "mode": "rgb",
            "label": "candidate object",
            "capabilities": {"subject": "object"},
        },
        headers=actor.headers,
    ).json()
    frame_asset_id = upload(api_client, actor, jpeg(), "object.jpg", "image/jpeg")
    for sequence in range(12):
        added = api_client.post(
            f"/api/v1/scans/{created['id']}/frames",
            json={
                "asset_id": frame_asset_id,
                "sequence_no": sequence,
                "kind": "rgb",
                "pose": {"azimuth_deg": sequence * 30},
                "quality": {"sharpness": 0.9},
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text

    qualities: list[str] = []

    class FakePhotoReconstructor:
        def reconstruct(self, scan: ScanInput, out_dir: Path) -> Reconstruction:
            quality = str(scan.quality)
            qualities.append(quality)
            out_dir.mkdir(parents=True, exist_ok=True)
            mesh_path = out_dir / f"{quality}.stl"
            trimesh.creation.icosphere(subdivisions=2).export(mesh_path)
            return Reconstruction(
                mesh_path=mesh_path,
                provider="photo-test",
                scale=ScaleReport(100, "scale_hint", 0.8, None),
                coverage=0.9,
                details={"quality": quality},
                format="stl",
            )

    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.reconstruction.reconstructor_for",
        lambda _provider: FakePhotoReconstructor(),
    )
    finalized = api_client.post(
        f"/api/v1/scans/{created['id']}/finalize",
        json={"scale_hint_mm": 100, "quality": "default"},
        headers=actor.headers,
    )
    assert finalized.status_code == 202, finalized.text
    (original_job,) = run_all(db_session, storage)
    assert original_job.status is JobStatus.succeeded, original_job.error
    original_asset_id = api_client.get(
        f"/api/v1/scans/{created['id']}", headers=actor.headers
    ).json()["mesh_asset_id"]

    queued = api_client.post(
        f"/api/v1/scans/{created['id']}/candidates", headers=actor.headers
    )
    assert queued.status_code == 202, queued.text
    assert len(queued.json()["jobs"]) == 2
    candidate_jobs = run_all(db_session, storage)
    assert len(candidate_jobs) == 2
    assert all(job.status is JobStatus.succeeded for job in candidate_jobs)

    candidates = api_client.get(
        f"/api/v1/scans/{created['id']}/candidates", headers=actor.headers
    )
    assert candidates.status_code == 200, candidates.text
    rows = candidates.json()
    assert [row["key"] for row in rows] == ["fast", "balanced", "detail"]
    assert all(row["status"] == "succeeded" and row["mesh_asset_id"] for row in rows)
    assert [row["quality"] for row in rows] == ["fast", "default", "dense"]
    assert qualities[0] == "default"
    assert sorted(qualities[1:]) == ["dense", "fast"]

    detail = next(row for row in rows if row["key"] == "detail")
    selected = api_client.post(
        f"/api/v1/scans/{created['id']}/candidates/select",
        json={"key": "detail"},
        headers=actor.headers,
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["mesh_asset_id"] == detail["mesh_asset_id"]
    assert selected.json()["mesh_asset_id"] != original_asset_id

    restored = api_client.post(
        f"/api/v1/scans/{created['id']}/candidates/select",
        json={"key": "balanced"},
        headers=actor.headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["mesh_asset_id"] == original_asset_id


def test_roomplan_geometry_becomes_the_accepted_projects_floor_plan(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The API integration image intentionally has no OCCT binary; production-kernel coverage
    # runs separately. Keep this test on the DB/storage/version attachment path.
    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.run_plan",
        lambda plan: SimpleNamespace(
            stl=stl(trimesh.creation.box(extents=(4_000, 3_000, 2_700))),
            kernel="OpenCASCADE-test",
        ),
    )
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "LiDAR room"},
        headers=actor.headers,
    ).json()["id"]
    scan = start_scanner_session(
        api_client,
        actor,
        project_id=project_id,
        label="Kitchen · RoomPlan (LiDAR)",
        capabilities={"depth_scan": True, "capture_source": "apple_roomplan"},
    )
    captured = api_client.put(
        f"/api/v1/scans/{scan['id']}/room-plan",
        json={
            "schema_version": 2,
            "room_id": "apple-room-1",
            "walls": [
                {
                    "identifier": "south",
                    "a_m": [0, 0],
                    "b_m": [4, 0],
                    "height_m": 2.7,
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 1.35, 0, 1],
                    "dimensions_m": [4, 2.7, 0.12],
                },
                {
                    "identifier": "east",
                    "a_m": [4, 0],
                    "b_m": [4, 3],
                    "height_m": 2.7,
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 4, 1.35, 1.5, 1],
                    "dimensions_m": [3, 2.7, 0.12],
                },
                {
                    "identifier": "north",
                    "a_m": [4, 3],
                    "b_m": [0, 3],
                    "height_m": 2.7,
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 1.35, 3, 1],
                    "dimensions_m": [4, 2.7, 0.12],
                },
                {
                    "identifier": "west",
                    "a_m": [0, 3],
                    "b_m": [0, 0],
                    "height_m": 2.7,
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1.35, 1.5, 1],
                    "dimensions_m": [3, 2.7, 0.12],
                },
            ],
            "openings": [
                {
                    "identifier": "door",
                    "parent_wall_id": "south",
                    "center_m": [2, 0],
                    "width_m": 0.9,
                    "kind": "door",
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 1.05, 0, 1],
                    "dimensions_m": [0.9, 2.1, 0.12],
                },
                {
                    "identifier": "window",
                    "parent_wall_id": "north",
                    "center_m": [2.5, 3],
                    "width_m": 1.2,
                    "kind": "window",
                    "transform_m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2.5, 1.5, 3, 1],
                    "dimensions_m": [1.2, 1.2, 0.12],
                },
            ],
        },
        headers=actor.headers,
    )
    assert captured.status_code == 200, captured.text
    assert captured.json()["floor_height_mm"] == 2_700
    assert len(captured.json()["floor_plan"]["openings"]) == 2

    # Generic progress telemetry cannot replace the validated geometry payload.
    overwritten = api_client.patch(
        f"/api/v1/scans/{scan['id']}/capture-stats",
        json={"stats": {"room_plan": {"floor_plan": {}}}},
        headers=actor.headers,
    )
    assert overwritten.status_code == 422

    mesh = trimesh.creation.box(extents=(4_000, 3_000, 2_700))
    room_usdz = tmp_path / "room.usdz"
    write_usdz(mesh, room_usdz)
    asset_id = upload(
        api_client,
        actor,
        room_usdz.read_bytes(),
        "room.usdz",
        "model/vnd.usdz+zip",
    )
    added = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "mesh"},
        headers=actor.headers,
    )
    assert added.status_code == 201, added.text
    finalized = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert finalized.status_code == 202, finalized.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["room_shell_asset_id"], ready["report"]["room_shell"]
    assert ready["report"]["room_shell"]["available"] is True
    shell = api_client.get(f"/api/v1/scans/{scan['id']}/room-shell", headers=actor.headers)
    assert shell.status_code == 200
    assert shell.json()["asset_id"] == ready["room_shell_asset_id"]
    kept = api_client.post(f"/api/v1/scans/{scan['id']}/accept", json={}, headers=actor.headers)
    assert kept.status_code == 200, kept.text

    version = db_session.get(ProjectVersion, uuid.UUID(kept.json()["result_version_id"]))
    assert version is not None
    assert version.provenance["room_plan"]["source"] == "apple_roomplan"
    assert version.provenance["room_plan"]["floor_height_mm"] == 2_700
    shell_link = (
        db_session.query(VersionAsset)
        .filter_by(version_id=version.id, role=AssetRole.room_shell)
        .one()
    )
    assert str(shell_link.asset_id) == ready["room_shell_asset_id"]
    plan = api_client.get(f"/api/v1/projects/{project_id}/floor-plan", headers=actor.headers)
    assert plan.status_code == 200, plan.text
    assert len(plan.json()["walls"]) == 4
    takeoff = api_client.get(
        f"/api/v1/projects/{project_id}/construction-takeoff", headers=actor.headers
    )
    assert takeoff.status_code == 200, takeoff.text
    takeoff_body = takeoff.json()
    quantities = {line["code"]: line["quantity"] for line in takeoff_body["quantities"]}
    assert quantities["footprint_area"] == pytest.approx(12)
    assert quantities["door_count"] == 1
    assert quantities["window_count"] == 1
    assert quantities["gross_wall_area"] == pytest.approx(37.8)
    assert takeoff_body["floor_height_mm"] == 2_700


def test_photo_room_requires_four_wall_coverage_orientation_and_measured_span(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = api_client.post(
        "/api/v1/scans",
        json={
            "workspace_id": str(actor.workspace.id),
            "mode": "rgb",
            "label": "Room without LiDAR",
            "capabilities": {
                "subject": "room",
                "capture_source": "room_photogrammetry_v1",
                "capture_plan": "four_wall_overlap_v1",
                "metric_scale": "user_measured_span",
            },
        },
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    scan_id = created.json()["id"]
    asset_id = upload(api_client, actor, jpeg(), "wall.jpg", "image/jpeg")
    sections = ("front", "right", "back", "left")
    sequence = 0
    for section in sections:
        for _index in range(8):
            added = api_client.post(
                f"/api/v1/scans/{scan_id}/frames",
                json={
                    "asset_id": asset_id,
                    "sequence_no": sequence,
                    "kind": "rgb",
                    "pose": {"room_section": section, "azimuth_deg": sequence * 5},
                },
                headers=actor.headers,
            )
            assert added.status_code == 201, added.text
            sequence += 1

    no_scale = api_client.post(
        f"/api/v1/scans/{scan_id}/finalize", json={}, headers=actor.headers
    )
    assert no_scale.status_code == 422
    assert no_scale.json()["error"]["details"]["required"] == "scale_hint_mm"

    finalized = api_client.post(
        f"/api/v1/scans/{scan_id}/finalize",
        json={"scale_hint_mm": 5_200, "scale_confidence": 0.99},
        headers=actor.headers,
    )
    assert finalized.status_code == 202, finalized.text

    class FakeRoomColmap:
        def reconstruct(self, _scan: object, out_dir: Path) -> Reconstruction:
            assert out_dir.name == "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            mesh_path = out_dir / "room_metric.ply"
            trimesh.creation.box(extents=(5_200, 3_400, 2_600)).export(mesh_path)
            context = out_dir / "room_texture_context.json"
            context.write_text("{}", encoding="utf-8")
            return Reconstruction(
                mesh_path=mesh_path,
                provider="colmap_room",
                scale=ScaleReport(
                    5_200,
                    "user_measured_room_span",
                    0.6,
                    "Scale comes from the measured maximum room span, not a depth sensor.",
                ),
                coverage=1.0,
                details={
                    "multi_view": {
                        "scene_kind": "room",
                        "registered_images": 32,
                        "registered_fraction": 1.0,
                    }
                },
                format="ply",
                texture_context_path=context,
            )

    def fake_reconstructor(provider: str) -> FakeRoomColmap:
        assert provider == "colmap_room"
        return FakeRoomColmap()

    def fake_texture(
        mesh: trimesh.Trimesh, _context: Path, _size: int, output: Path
    ) -> dict[str, object]:
        payload = trimesh.Scene(mesh).export(file_type="glb")
        output.write_bytes(payload if isinstance(payload, bytes) else bytes(payload))
        return {"texture_baked": True, "photo_projected_faces": len(mesh.faces)}

    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.reconstruction.reconstructor_for", fake_reconstructor
    )
    monkeypatch.setattr(
        "app.jobs.reconstruct_scan.exterior.export_projected_texture_glb", fake_texture
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/scans/{scan_id}", headers=actor.headers).json()
    assert ready["report"]["provider"] == "colmap_room"
    assert ready["report"]["scale"]["source"] == "user_measured_room_span"
    assert ready["report"]["scale"]["confidence"] == 0.6
    assert ready["report"]["multi_view"]["registered_images"] == 32
    assert ready["mesh_asset_id"] is not None


def test_photo_room_rejects_missing_wall_section_before_job(
    api_client: TestClient,
    actor: Actor,
) -> None:
    created = api_client.post(
        "/api/v1/scans",
        json={
            "workspace_id": str(actor.workspace.id),
            "mode": "rgb",
            "capabilities": {
                "subject": "room",
                "capture_source": "room_photogrammetry_v1",
            },
        },
        headers=actor.headers,
    ).json()
    asset_id = upload(api_client, actor, jpeg(), "wall.jpg", "image/jpeg")
    for sequence in range(24):
        section = ("front", "right", "back")[sequence // 8]
        added = api_client.post(
            f"/api/v1/scans/{created['id']}/frames",
            json={
                "asset_id": asset_id,
                "sequence_no": sequence,
                "kind": "rgb",
                "pose": {"room_section": section, "azimuth_deg": sequence * 5},
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text
    # A forged non-RGB frame cannot satisfy wall-photo coverage.
    for sequence in range(24, 32):
        added = api_client.post(
            f"/api/v1/scans/{created['id']}/frames",
            json={
                "asset_id": asset_id,
                "sequence_no": sequence,
                "kind": "depth",
                "pose": {"room_section": "left", "azimuth_deg": sequence * 5},
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text
    finalized = api_client.post(
        f"/api/v1/scans/{created['id']}/finalize",
        json={"scale_hint_mm": 5_200},
        headers=actor.headers,
    )
    assert finalized.status_code == 422
    assert finalized.json()["error"]["details"]["missing_sections"] == ["left"]


def test_a_scanner_session_accepts_one_fused_mesh_and_refuses_photos_as_fragments(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    scan = start_scanner_session(api_client, actor)
    whole = trimesh.creation.box(extents=(50, 20, 10))
    asset_id = upload(api_client, actor, stl(whole), "whole.stl", "model/stl")
    # a mesh file cannot pose as a photo frame...
    wrong = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "rgb"},
        headers=actor.headers,
    )
    assert wrong.status_code == 422
    # ...and a single fused mesh is a complete scanner session
    added = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "mesh"},
        headers=actor.headers,
    )
    assert added.status_code == 201, added.text
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": "80"},  # the user's guess; the scanner knows better
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["report"]["scale"]["applied_mm"] == 50.0
    assert "80" in ready["report"]["scale"]["warning"]


def test_a_demo_scan_feeds_a_scanner_session_and_reconstructs(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    """F-082 without a device: the server's simulated turntable delivers the fragments."""
    response = api_client.post(
        "/api/v1/scans/demo",
        json={"workspace_id": str(actor.workspace.id), "label": "demo bracket"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["scan"]["mode"] == "scanner" and body["job"]["type"] == "demo_scan"
    scan_id = body["scan"]["id"]

    # the demo job (no pause in tests) adds eight fragments and finalizes; then reconstruction
    from app.models.execution import Job

    demo = db_session.get(Job, uuid.UUID(body["job"]["job_id"]))
    assert demo is not None
    demo.input = {**demo.input, "pause_s": 0}
    db_session.flush()
    done = run_all(db_session, storage)
    assert [job.type for job in done] == ["demo_scan", "reconstruct_scan"]
    assert all(job.status is JobStatus.succeeded for job in done), [j.error for j in done]

    scan = api_client.get(f"/api/v1/scans/{scan_id}", headers=actor.headers).json()
    assert scan["frame_count"] == 8 and scan["status"] == "ready"
    assert scan["capture_stats"]["fragments"] == 8
    frames = api_client.get(f"/api/v1/scans/{scan_id}/frames", headers=actor.headers).json()
    assert scan["capture_stats"]["faces"] == sum(frame["quality"]["faces"] for frame in frames)
    report = scan["report"]
    assert report["scale"]["source"] == "device"
    assert abs(report["scale"]["applied_mm"] - 120) < 1
    project = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Demo bracket"},
        headers=actor.headers,
    )
    assert project.status_code == 201
    kept = api_client.post(
        f"/api/v1/scans/{scan_id}/accept",
        json={"project_id": project.json()["id"]},
        headers=actor.headers,
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["result_version_id"] is not None


def test_canceled_demo_does_not_add_fragments(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    response = api_client.post(
        "/api/v1/scans/demo",
        json={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert response.status_code == 202
    scan_id = response.json()["scan"]["id"]
    job_id = response.json()["job"]["job_id"]
    canceled = api_client.post(f"/api/v1/scans/{scan_id}/cancel", headers=actor.headers)
    assert canceled.status_code == 200
    assert run_all(db_session, storage) == []
    job = db_session.get(Job, uuid.UUID(job_id))
    assert job is not None and job.status is JobStatus.canceled and job.cancel_requested
    scan = api_client.get(f"/api/v1/scans/{scan_id}", headers=actor.headers).json()
    assert scan["status"] == "canceled" and scan["frame_count"] == 0
    assert scan["mesh_asset_id"] is None


def test_canceling_a_finalized_scan_cancels_its_reconstruction_job(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    scan = start_scanner_session(api_client, actor)
    asset_id = upload(
        api_client,
        actor,
        stl(trimesh.creation.box(extents=(50, 20, 10))),
        "whole.stl",
        "model/stl",
    )
    added = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": asset_id, "sequence_no": 0, "kind": "mesh"},
        headers=actor.headers,
    )
    assert added.status_code == 201, added.text
    finalized = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert finalized.status_code == 202, finalized.text

    canceled = api_client.post(f"/api/v1/scans/{scan['id']}/cancel", headers=actor.headers)
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"
    assert run_all(db_session, storage) == []

    job = db_session.get(Job, uuid.UUID(finalized.json()["job_id"]))
    assert job is not None and job.status is JobStatus.canceled and job.cancel_requested
