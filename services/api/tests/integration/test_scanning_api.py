"""E9 scan path: session -> resumable frames -> finalize -> reconstruction -> accept."""

from __future__ import annotations

import hashlib
import struct
import uuid
import zlib
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.jobs import runner
from app.models import Asset, ProjectVersion, ScanFrame, ScanSession
from app.models.core import Units
from app.models.execution import JobStatus
from app.models.versioning import AssetKind
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


def png_bytes(seed: int) -> bytes:
    """A real 2x2 PNG — the upload path checks magic bytes, so a fake would be rejected."""
    raw = b"".join(
        bytes([0]) + bytes([(seed + x) % 256, (seed * 2) % 256, x % 256]) * 2 for x in range(2)
    )

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def frame_assets(db_session: Session, storage: S3Storage) -> Iterator[list[Asset]]:
    """Upload N frame images straight to storage and register them as assets."""
    assets: list[Asset] = []
    keys: list[str] = []

    def make(workspace_id: uuid.UUID, count: int) -> list[Asset]:
        for index in range(count):
            data = png_bytes(index)
            sha = hashlib.sha256(data).hexdigest()
            key = storage.object_key(workspace_id, sha, "png")
            storage.put(key, data, "image/png")
            keys.append(key)
            asset = Asset(
                workspace_id=workspace_id,
                kind=AssetKind.original,
                sha256=sha,
                storage_key=key,
                mime="image/png",
                format="png",
                byte_size=len(data),
                units=Units.mm,
                metadata_={"filename": f"frame_{index}.png"},
            )
            db_session.add(asset)
            assets.append(asset)
        db_session.flush()
        return assets

    make.assets = assets  # type: ignore[attr-defined]
    yield make  # type: ignore[misc]
    for key in keys:
        storage.delete(key)


def start_scan(api_client: TestClient, actor: Actor, **body: Any) -> dict[str, Any]:
    response = api_client.post(
        "/api/v1/scans",
        json={"workspace_id": str(actor.workspace.id), **body},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def add_frames(
    api_client: TestClient, actor: Actor, scan_id: str, assets: list[Asset], **extra: Any
) -> None:
    for index, asset in enumerate(assets):
        response = api_client.post(
            f"/api/v1/scans/{scan_id}/frames",
            json={"asset_id": str(asset.id), "sequence_no": index, **extra},
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text


def run_all(db: Session, storage: S3Storage) -> list[Any]:
    done = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


# --- T-078 resumable upload -------------------------------------------------------------------


def test_resent_frame_is_not_a_duplicate(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    frame_assets: Any,
) -> None:
    assets = frame_assets(actor.workspace.id, 3)
    scan = start_scan(api_client, actor, label="mug")
    add_frames(api_client, actor, scan["id"], assets)

    # The phone lost the response and sends frame 1 again.
    again = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": str(assets[1].id), "sequence_no": 1},
        headers=actor.headers,
    )
    assert again.status_code == 201
    assert len(db_session.query(ScanFrame).all()) == 3

    session = db_session.get(ScanSession, uuid.UUID(scan["id"]))
    assert session is not None
    db_session.refresh(session)
    assert session.frame_count == 3  # maintained by the trigger

    # A different image under a number that is taken is a conflict, not a silent overwrite.
    clash = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": str(assets[2].id), "sequence_no": 1},
        headers=actor.headers,
    )
    assert clash.status_code == 409


def test_a_frame_must_be_an_image(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    scan = start_scan(api_client, actor)
    model = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256="a" * 64,
        storage_key="ws/x/model.stl",
        mime="model/stl",
        format="stl",
        byte_size=10,
        units=Units.mm,
    )
    db_session.add(model)
    db_session.flush()
    response = api_client.post(
        f"/api/v1/scans/{scan['id']}/frames",
        json={"asset_id": str(model.id), "sequence_no": 0},
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --- T-079..T-084 finalize, reconstruct, accept ------------------------------------------------


def test_finalize_needs_enough_frames(
    api_client: TestClient, actor: Actor, frame_assets: Any
) -> None:
    assets = frame_assets(actor.workspace.id, 4)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)
    response = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert response.status_code == 422
    assert "at least" in response.json()["error"]["message"]


def test_large_scale_hint_is_reserved_for_exterior_scans(
    api_client: TestClient, actor: Actor, frame_assets: Any
) -> None:
    assets = frame_assets(actor.workspace.id, 12)
    scan = start_scan(api_client, actor, label="ordinary object")
    add_frames(api_client, actor, scan["id"], assets)

    response = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": 12_000},
        headers=actor.headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["maximum"] == 10_000


def test_exterior_finalize_requires_facade_coverage_pose_and_metric_scale(
    api_client: TestClient, actor: Actor, frame_assets: Any
) -> None:
    assets = frame_assets(actor.workspace.id, 32)
    scan = start_scan(
        api_client,
        actor,
        label="building exterior",
        capabilities={"subject": "exterior", "metric_scale": "none"},
    )
    sections = ("front", "right", "back", "left")

    for index, asset in enumerate(assets[:24]):
        response = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": str(asset.id),
                "sequence_no": index,
                "pose": {
                    "azimuth_deg": index * 5,
                    "exterior_section": sections[index // 8],
                },
            },
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text

    uncovered = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": 12_000},
        headers=actor.headers,
    )
    assert uncovered.status_code == 422
    assert uncovered.json()["error"]["details"]["missing_sections"] == ["left"]

    for index, asset in enumerate(assets[24:], start=24):
        response = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": str(asset.id),
                "sequence_no": index,
                "pose": {"azimuth_deg": index * 5, "exterior_section": "left"},
            },
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text

    no_scale = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert no_scale.status_code == 422
    assert no_scale.json()["error"]["details"]["required"] == "scale_hint_mm"

    ready = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": 12_000, "scale_confidence": 0.8},
        headers=actor.headers,
    )
    assert ready.status_code == 202, ready.text


# --- scan quality options (method/quality/texture/maskObject) ---------------------------------


def test_finalize_rejects_unknown_quality_and_texture_values(
    api_client: TestClient, actor: Actor, frame_assets: Any
) -> None:
    assets = frame_assets(actor.workspace.id, 12)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)

    bad_quality = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"quality": "ultra"},
        headers=actor.headers,
    )
    assert bad_quality.status_code == 422

    bad_texture = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"texture": 777},
        headers=actor.headers,
    )
    assert bad_texture.status_code == 422

    bad_method = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"method": "nerf"},
        headers=actor.headers,
    )
    assert bad_method.status_code == 422


def test_finalize_accepts_processing_options_and_reconstruction_honors_them(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worker import masking

    def mask_without_loading_live_weights(
        frames: tuple[Any, ...], _out_dir: Any
    ) -> masking.MaskingResult:
        return masking.MaskingResult(
            frames=frames,
            report={
                "mask_applied": True,
                "model": "u2net",
                "frames_masked": len([frame for frame in frames if frame.kind == "rgb"]),
                "foreground_fraction_min": 0.31,
                "foreground_fraction_max": 0.74,
            },
        )

    monkeypatch.setattr(masking, "mask_frames", mask_without_loading_live_weights)
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor, label="mug")
    add_frames(api_client, actor, scan["id"], assets, quality={"sharpness": 0.8})

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={
            "scale_hint_mm": "95.0",
            "scale_confidence": "0.7",
            "quality": "fast",
            "texture": 1024,
            "mask_object": True,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    # T-xxx: the options chosen before processing come back with the result.
    assert ready["processing_options"] == {
        "method": "photogrammetry",
        "quality": "fast",
        "texture": 1024,
        "mask_object": True,
    }
    report = ready["report"]
    assert report["decimate"]["quality"] == "fast"
    assert report["decimate"]["weight"] == 0.1
    assert report["decimate"]["result_faces"] < report["decimate"]["native_faces"]
    # STL carries no colour, so a texture bake is honestly reported as impossible, not faked.
    assert report["texture"] == {"texture_baked": False, "reason": "no_color_data"}
    assert report["mask"] == {
        "mask_applied": True,
        "model": "u2net",
        "frames_masked": 14,
        "foreground_fraction_min": 0.31,
        "foreground_fraction_max": 0.74,
    }


def test_raw_quality_skips_decimation_entirely(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
) -> None:
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"quality": "raw"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    report = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()["report"]
    assert report["decimate"]["weight"] == 1.0
    assert "target_faces" not in report["decimate"]  # no simplification step ran at all
    assert report["decimate"]["result_faces"] == report["decimate"]["native_faces"]


def test_requested_masking_fails_closed_when_no_subject_can_be_segmented(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worker import masking

    def refuse_background(_frames: tuple[Any, ...], _out_dir: Any) -> masking.MaskingResult:
        raise masking.MaskingError(
            "mask_no_background", "the subject cannot be separated from the background"
        )

    monkeypatch.setattr(masking, "mask_frames", refuse_background)
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)
    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"mask_object": True},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert job.error is not None and job.error["code"] == "mask_no_background"
    failed = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "mask_no_background"


def test_gaussian_splat_is_not_supported_yet(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
) -> None:
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"method": "gaussian_splat"},
        headers=actor.headers,
    )
    # finalize queues the job; the job itself refuses the unsupported method (reconstruction
    # is not attempted at all, so no mesh is silently produced with the wrong method).
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert job.error is not None
    assert job.error["code"] == "not_supported_yet"

    scan_after = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert scan_after["status"] == "failed"
    assert scan_after["error"]["code"] == "not_supported_yet"


def test_exterior_scan_uses_connected_multiview_provider_and_becomes_editable(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worker import reconstruction

    def fake_colmap(
        _self: Any, scan_input: reconstruction.ScanInput, out_dir: Any
    ) -> reconstruction.Reconstruction:
        import json
        import shutil

        import numpy as np
        import trimesh
        from scipy.spatial.transform import Rotation
        from trimesh.visual import ColorVisuals

        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "exterior.ply"
        mesh = trimesh.creation.box(extents=(12_000, 7_000, 4_000))
        mesh.unmerge_vertices()
        mesh.visual = ColorVisuals(
            mesh=mesh,
            face_colors=[(170, 110, 60, 255)] * len(mesh.faces),
        )
        mesh.export(mesh_path)
        images = out_dir / "images"
        images.mkdir()
        positions = {
            "front": np.asarray([0.0, -20_000.0, 0.0]),
            "right": np.asarray([20_000.0, 0.0, 0.0]),
            "back": np.asarray([0.0, 20_000.0, 0.0]),
            "left": np.asarray([-20_000.0, 0.0, 0.0]),
        }
        cameras = []
        for section, camera_centre in positions.items():
            filename = f"{section}.png"
            shutil.copyfile(scan_input.frames[0].path, images / filename)
            forward = -camera_centre / np.linalg.norm(camera_centre)
            right = np.cross(forward, np.asarray([0.0, 0.0, 1.0]))
            down = np.cross(forward, right)
            rotation = np.stack([right, down, forward])
            qx, qy, qz, qw = Rotation.from_matrix(rotation).as_quat()
            cameras.append(
                {
                    "filename": filename,
                    "section": section,
                    "qvec": [qw, qx, qy, qz],
                    "tvec": (-rotation @ camera_centre).tolist(),
                    "model": "SIMPLE_PINHOLE",
                    "width": 2,
                    "height": 2,
                    "params": [0.1, 0.5, 0.5],
                }
            )
        context_path = out_dir / "exterior_texture_context.json"
        context_path.write_text(
            json.dumps(
                {
                    "cameras": cameras,
                    "source_from_platform": np.eye(4).tolist(),
                }
            ),
            encoding="utf-8",
        )
        return reconstruction.Reconstruction(
            mesh_path=mesh_path,
            provider="colmap_exterior",
            scale=reconstruction.ScaleReport(12_000, "measured_max_dimension", 0.8),
            coverage=1.0,
            details={
                "frames": len(scan_input.frames),
                "placeholder": False,
                "multi_view": {
                    "engine": "colmap",
                    "registered_images": len(scan_input.frames),
                    "registered_by_section": {
                        section: 8 for section in ("front", "right", "back", "left")
                    },
                    "mean_reprojection_error_px": 0.44,
                },
            },
            format="ply",
            texture_context_path=context_path,
        )

    monkeypatch.setattr(reconstruction.ColmapExteriorReconstructor, "reconstruct", fake_colmap)
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Exterior"},
        headers=actor.headers,
    ).json()["id"]
    assets = frame_assets(actor.workspace.id, 32)
    scan = start_scan(
        api_client,
        actor,
        project_id=project_id,
        label="building exterior",
        capabilities={"subject": "exterior", "metric_scale": "none"},
    )
    sections = ("front", "right", "back", "left")
    for index, asset in enumerate(assets):
        response = api_client.post(
            f"/api/v1/scans/{scan['id']}/frames",
            json={
                "asset_id": str(asset.id),
                "sequence_no": index,
                "pose": {
                    "azimuth_deg": index * 5,
                    "exterior_section": sections[index // 8],
                },
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

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    scan_after = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert scan_after["status"] == "ready"
    assert scan_after["report"]["provider"] == "colmap_exterior"
    assert scan_after["report"]["placeholder"] is False
    assert scan_after["report"]["multi_view"]["registered_images"] == 32
    assert scan_after["report"]["texture"]["texture_baked"] is True
    assert scan_after["report"]["texture"]["atlas_source_photos"] >= 1
    assert scan_after["report"]["texture"]["photo_projected_faces"] >= 1
    assert scan_after["report"]["scale"] == {
        "applied_mm": 12_000.0,
        "source": "measured_max_dimension",
        "confidence": 0.8,
        "warning": None,
    }
    accepted_version = api_client.post(
        f"/api/v1/scans/{scan['id']}/accept",
        json={"label": "Exterior building"},
        headers=actor.headers,
    )
    assert accepted_version.status_code == 200, accepted_version.text
    version = db_session.get(
        ProjectVersion, uuid.UUID(accepted_version.json()["result_version_id"])
    )
    assert version is not None and version.project_id == uuid.UUID(project_id)
    textured = db_session.get(Asset, uuid.UUID(scan_after["mesh_asset_id"]))
    assert textured is not None and textured.format == "glb"


def test_scan_reconstructs_and_becomes_a_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
) -> None:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "scans"},
        headers=actor.headers,
    ).json()["id"]

    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor, project_id=project_id, label="mug")
    add_frames(api_client, actor, scan["id"], assets, quality={"sharpness": 0.8})

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": "95.0", "scale_confidence": "0.7"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    assert ready["mesh_asset_id"]
    report = ready["report"]
    assert report["provider"] == "stub"
    assert report["scale"]["source"] == "scale_hint"
    assert report["scale"]["applied_mm"] == pytest.approx(95.0, abs=0.01)
    assert report["capture"]["frames"] == 14
    assert report["repair"]  # T-083: cleanup ran and is reported

    # T-084: nothing lands in the project until the user accepts it.
    assert db_session.query(ProjectVersion).filter_by(project_id=uuid.UUID(project_id)).count() == 0
    kept = api_client.post(
        f"/api/v1/scans/{scan['id']}/accept", json={"label": "Scanned mug"}, headers=actor.headers
    )
    assert kept.status_code == 200, kept.text
    body = kept.json()
    assert body["status"] == "accepted"

    version = db_session.get(ProjectVersion, uuid.UUID(body["result_version_id"]))
    assert version is not None
    assert version.label == "Scanned mug"
    assert version.provenance["operation"] == "scan"
    assert version.provenance["frames"] == 14
    assert [a.asset_id for a in version.assets] == [uuid.UUID(ready["mesh_asset_id"])]


def test_without_a_size_the_scan_says_the_scale_is_assumed(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
) -> None:
    assets = frame_assets(actor.workspace.id, 12)
    scan = start_scan(api_client, actor)
    add_frames(api_client, actor, scan["id"], assets)
    api_client.post(f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error

    report = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()["report"]
    assert report["scale"]["source"] == "assumed"
    assert report["scale"]["confidence"] <= 0.2
    assert "Measure the object" in report["scale"]["warning"]


def test_a_stranger_cannot_see_or_touch_a_scan(
    api_client: TestClient, actor: Actor, db_session: Session, frame_assets: Any
) -> None:
    scan = start_scan(api_client, actor)
    stranger = make_actor(db_session)
    assert (
        api_client.get(f"/api/v1/scans/{scan['id']}", headers=stranger.headers).status_code == 404
    )
    assert (
        api_client.post(
            f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=stranger.headers
        ).status_code
        == 404
    )


def test_pictures_from_the_photo_library_reconstruct_without_a_claimed_pose(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    frame_assets: Any,
) -> None:
    """The phone's orientation says nothing about where a library picture was taken, so the
    client sends no azimuth for it; the scan must still reconstruct and must not invent one."""
    assets = frame_assets(actor.workspace.id, 14)
    scan = start_scan(api_client, actor, label="from the gallery")
    library_pose = {
        "pose_source": "none",
        "position_available": False,
        "gps_used_for_geometry": False,
        "depth_available": False,
        "source": "photo_library",
    }
    add_frames(
        api_client,
        actor,
        scan["id"],
        assets,
        pose=library_pose,
        quality={"sharpness": 0.6, "method": "jpeg_size_proxy", "source": "photo_library"},
    )
    stored = db_session.query(ScanFrame).filter_by(scan_session_id=uuid.UUID(scan["id"])).all()
    assert len(stored) == 14
    assert all("azimuth_deg" not in (frame.pose or {}) for frame in stored)

    accepted = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize",
        json={"scale_hint_mm": "95.0", "scale_confidence": "0.7"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/scans/{scan['id']}", headers=actor.headers).json()
    assert ready["status"] == "ready"
    assert ready["report"]["capture"]["frames"] == 14
