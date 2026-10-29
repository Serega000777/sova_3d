"""T-064/T-067 analyze/optimize-print jobs; T-068..T-072 catalogue, profiles and
profile-aware analysis."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.jobs import runner
from app.models import Asset, Job, PrintAnalysisRecord, Project, ProjectVersion
from app.models.core import Units
from app.models.execution import JobStatus
from app.models.versioning import AssetKind, AssetRole, VersionAsset
from app.services import printer_bridge, projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor, test_s3_settings


def t_shape_stl() -> bytes:
    post = trimesh.creation.box(extents=(10, 10, 30))
    post.apply_translation((0, 0, 15))
    bar = trimesh.creation.box(extents=(50, 10, 5))
    bar.apply_translation((0, 0, 32.5))
    mesh = trimesh.boolean.union([post, bar])
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else bytes(exported)


def seed_version(
    db: Session, storage: S3Storage, actor: Actor, payload: bytes
) -> tuple[Project, ProjectVersion, Asset]:
    project = projects.create_project(
        db, user_id=actor.user.id, workspace_id=actor.workspace.id, name="print-me"
    )
    sha = hashlib.sha256(payload).hexdigest()
    key = S3Storage.object_key(actor.workspace.id, sha, "stl")
    storage.put(key, payload, "model/stl")
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=sha,
        storage_key=key,
        mime="model/stl",
        format="stl",
        byte_size=len(payload),
        units=Units.mm,
    )
    db.add(asset)
    db.flush()
    version = projects.create_version(
        db, user_id=actor.user.id, project_id=project.id, assets={AssetRole.model: asset.id}
    )
    return project, version, asset


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def run_all(db: Session, storage: S3Storage) -> list[Job]:
    done: list[Job] = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


# --- T-068 / T-069 catalogue -----------------------------------------------------------------


def test_catalogue_seeds(api_client: TestClient, actor: Actor) -> None:
    models = api_client.get("/api/v1/printer-models", headers=actor.headers).json()
    vendors = {m["vendor"] for m in models}
    assert {"Bambu Lab", "Prusa", "Creality"} <= vendors and len(models) >= 10
    x1c = next(m for m in models if m["id"] == "bambu-x1c")
    assert float(x1c["bed_x_mm"]) == 256 and x1c["technology"] == "fdm"

    materials = api_client.get("/api/v1/materials", headers=actor.headers).json()
    assert {m["kind"] for m in materials} == {"PLA", "PETG", "ABS", "TPU", "ASA"}
    pla = next(m for m in materials if m["id"] == "pla")
    assert float(pla["density_g_cm3"]) == pytest.approx(1.24)


# --- T-070 profiles -------------------------------------------------------------------------


def test_printer_profile_crud_is_workspace_scoped(
    api_client: TestClient, db_session: Session
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    created = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(owner.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Desk MINI",
            "nozzle_mm": "0.6",
            "default_material_id": "petg",
            "raft_density_profiles": {
                "petg": {"base_density_pct": 35, "interface_density_pct": 80}
            },
            "is_default": True,
        },
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["is_default"] and float(profile["nozzle_mm"]) == 0.6
    assert float(profile["layer_height_mm"]) == 0.2  # default
    assert profile["raft_density_profiles"]["petg"] == {
        "base_density_pct": 35.0,
        "interface_density_pct": 80.0,
    }

    second = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(owner.workspace.id),
            "printer_model_id": "bambu-x1c",
            "name": "Big one",
            "is_default": True,
        },
        headers=owner.headers,
    ).json()
    listed = api_client.get(
        "/api/v1/printer-profiles",
        params={"workspace_id": str(owner.workspace.id)},
        headers=owner.headers,
    ).json()
    assert [p["is_default"] for p in listed] == [True, False]  # only one default
    assert listed[0]["id"] == second["id"]

    updated = api_client.put(
        f"/api/v1/printer-profiles/{profile['id']}",
        json={"name": "Desk MINI+", "layer_height_mm": "0.15"},
        headers=owner.headers,
    ).json()
    assert updated["name"] == "Desk MINI+" and float(updated["layer_height_mm"]) == 0.15

    bad_model = api_client.post(
        "/api/v1/printer-profiles",
        json={"workspace_id": str(owner.workspace.id), "printer_model_id": "nope", "name": "x"},
        headers=owner.headers,
    )
    assert bad_model.status_code == 404

    unknown_material = api_client.put(
        f"/api/v1/printer-profiles/{profile['id']}",
        json={
            "raft_density_profiles": {
                "unobtainium": {"base_density_pct": 25, "interface_density_pct": 100}
            }
        },
        headers=owner.headers,
    )
    assert unknown_material.status_code == 404
    out_of_bounds = api_client.put(
        f"/api/v1/printer-profiles/{profile['id']}",
        json={
            "raft_density_profiles": {"pla": {"base_density_pct": 71, "interface_density_pct": 100}}
        },
        headers=owner.headers,
    )
    assert out_of_bounds.status_code == 422
    forbidden_update = api_client.put(
        f"/api/v1/printer-profiles/{profile['id']}",
        json={
            "raft_density_profiles": {"pla": {"base_density_pct": 25, "interface_density_pct": 100}}
        },
        headers=stranger.headers,
    )
    assert forbidden_update.status_code == 404

    for method, path in (
        ("get", f"/api/v1/printer-profiles/{profile['id']}"),
        ("delete", f"/api/v1/printer-profiles/{profile['id']}"),
    ):
        response = getattr(api_client, method)(path, headers=stranger.headers)
        assert response.status_code == 404
    assert (
        api_client.get(
            "/api/v1/printer-profiles",
            params={"workspace_id": str(owner.workspace.id)},
            headers=stranger.headers,
        ).status_code
        == 404
    )
    assert (
        api_client.delete(
            f"/api/v1/printer-profiles/{profile['id']}", headers=owner.headers
        ).status_code
        == 204
    )


def _metric_version(
    db: Session,
    actor: Actor,
    *,
    name: str,
    size_mm: list[float],
    volume_mm3: float,
) -> ProjectVersion:
    project = projects.create_project(
        db, user_id=actor.user.id, workspace_id=actor.workspace.id, name=name
    )
    return projects.create_version(
        db,
        user_id=actor.user.id,
        project_id=project.id,
        provenance={
            "bodies": [
                {
                    "name": "result",
                    "bbox_mm": {"size": size_mm},
                    "volume_mm3": volume_mm3,
                    "valid": True,
                }
            ]
        },
    )


def test_print_farm_plan_nests_batch_and_balances_concrete_printers(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    first = _metric_version(
        db_session, actor, name="bracket", size_mm=[80, 60, 20], volume_mm3=24_000
    )
    second = _metric_version(
        db_session, actor, name="housing", size_mm=[100, 70, 30], volume_mm3=42_000
    )
    profile_ids = []
    for model, name in (("bambu-x1c", "Fast X1"), ("prusa-mini", "MINI farm")):
        created = api_client.post(
            "/api/v1/printer-profiles",
            json={
                "workspace_id": str(actor.workspace.id),
                "printer_model_id": model,
                "name": name,
            },
            headers=actor.headers,
        )
        assert created.status_code == 201, created.text
        profile_ids.append(created.json()["id"])

    response = api_client.post(
        "/api/v1/print-farm/plan",
        json={
            "workspace_id": str(actor.workspace.id),
            "items": [
                {"version_id": str(first.id), "quantity": 4},
                {"version_id": str(second.id), "quantity": 2},
            ],
            "printer_profile_ids": profile_ids,
            "material_id": "petg",
            "infill_density_pct": 30,
            "wall_count": 3,
            "margin_mm": 5,
            "gap_mm": 8,
        },
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["item_count"] == 6
    assert plan["plate_count"] >= 2
    assert plan["dispatch_ready"] is False
    assert plan["estimated_material_g"] > 0
    assert plan["estimated_material_cost"] > 0
    assert len(plan["assignments"]) == 2
    placements = [
        placement
        for assignment in plan["assignments"]
        for plate in assignment["plates"]
        for placement in plate["placements"]
    ]
    assert len(placements) == 6
    assert {placement["project_name"] for placement in placements} == {"bracket", "housing"}
    assert all(placement["plate_rotation_deg"] in (0, 90) for placement in placements)

    saved = api_client.put(
        "/api/v1/print-farm/queue",
        json={"workspace_id": str(actor.workspace.id), "base_revision": 0, "plan": plan},
        headers=actor.headers,
    )
    assert saved.status_code == 200, saved.text
    queue = saved.json()
    assert queue["revision"] == 1 and queue["plan"] == plan
    restored = api_client.get(
        "/api/v1/print-farm/queue",
        params={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert restored.status_code == 200 and restored.json()["id"] == queue["id"]

    updated = api_client.put(
        "/api/v1/print-farm/queue",
        json={"workspace_id": str(actor.workspace.id), "base_revision": 1, "plan": plan},
        headers=actor.headers,
    )
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    stale = api_client.put(
        "/api/v1/print-farm/queue",
        json={"workspace_id": str(actor.workspace.id), "base_revision": 1, "plan": plan},
        headers=actor.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == 2

    forged = {**plan, "assignments": [dict(item) for item in plan["assignments"]]}
    forged["assignments"][0] = {
        **forged["assignments"][0],
        "printer_name": "Forged printer",
    }
    refused = api_client.put(
        "/api/v1/print-farm/queue",
        json={"workspace_id": str(actor.workspace.id), "base_revision": 2, "plan": forged},
        headers=actor.headers,
    )
    assert refused.status_code == 422
    forged_total = {**plan, "estimated_material_cost": 0}
    refused_total = api_client.put(
        "/api/v1/print-farm/queue",
        json={"workspace_id": str(actor.workspace.id), "base_revision": 2, "plan": forged_total},
        headers=actor.headers,
    )
    assert refused_total.status_code == 422

    stranger = make_actor(db_session)
    hidden = api_client.post(
        "/api/v1/print-farm/plan",
        json={
            "workspace_id": str(actor.workspace.id),
            "items": [{"version_id": str(first.id), "quantity": 1}],
            "printer_profile_ids": profile_ids,
        },
        headers=stranger.headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"
    assert (
        api_client.get(
            "/api/v1/print-farm/queue",
            params={"workspace_id": str(actor.workspace.id)},
            headers=stranger.headers,
        ).status_code
        == 404
    )

    deleted = api_client.delete(
        "/api/v1/print-farm/queue",
        params={"workspace_id": str(actor.workspace.id), "base_revision": 2},
        headers=actor.headers,
    )
    assert deleted.status_code == 204


def test_print_farm_plan_fails_closed_for_unmeasured_or_oversized_versions(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    profile = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Small bed",
        },
        headers=actor.headers,
    ).json()
    project = projects.create_project(
        db_session,
        user_id=actor.user.id,
        workspace_id=actor.workspace.id,
        name="unknown",
    )
    unmeasured = projects.create_version(db_session, user_id=actor.user.id, project_id=project.id)
    oversized = _metric_version(
        db_session, actor, name="too tall", size_mm=[100, 100, 400], volume_mm3=100_000
    )

    common = {
        "workspace_id": str(actor.workspace.id),
        "printer_profile_ids": [profile["id"]],
    }
    missing = api_client.post(
        "/api/v1/print-farm/plan",
        json={**common, "items": [{"version_id": str(unmeasured.id), "quantity": 1}]},
        headers=actor.headers,
    )
    assert missing.status_code == 422
    assert (
        missing.json()["error"]["message"]
        == "version has no trusted metric bounds for batch planning"
    )

    does_not_fit = api_client.post(
        "/api/v1/print-farm/plan",
        json={**common, "items": [{"version_id": str(oversized.id), "quantity": 1}]},
        headers=actor.headers,
    )
    assert does_not_fit.status_code == 422
    assert does_not_fit.json()["error"]["message"] == "batch item does not fit any selected printer"


def test_generated_gcode_can_be_sent_through_test_printer_bridge(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    profile = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Network printer",
        },
        headers=actor.headers,
    ).json()
    payload = b"; generated by test\nG28\nM84\n"
    sha = hashlib.sha256(payload).hexdigest()
    key = S3Storage.object_key(actor.workspace.id, sha, "gcode")
    storage.put(key, payload, "text/x-gcode")
    cleanup_keys.append(key)
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.derived,
        sha256=sha,
        storage_key=key,
        mime="text/x-gcode",
        format="gcode",
        byte_size=len(payload),
        units=Units.mm,
        metadata_={"filename": "owl test.gcode"},
        created_by=actor.user.id,
    )
    db_session.add(asset)
    db_session.flush()

    capability = api_client.get("/api/v1/printer-bridge", headers=actor.headers)
    assert capability.status_code == 200
    assert capability.json() == {
        "enabled": True,
        "provider": "stub",
        "test_mode": True,
        "can_start": True,
        "has_camera": True,
    }
    sent = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/print-jobs",
        json={
            "workspace_id": str(actor.workspace.id),
            "asset_id": str(asset.id),
            "start": True,
        },
        headers=actor.headers,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json() == {
        "provider": "stub",
        "filename": "owl-test.gcode",
        "selected": True,
        "printing": True,
        "remote_path": "local/owl-test.gcode",
        "message": "Test upload completed; no real printer was contacted.",
    }


def test_octoprint_bridge_keeps_key_server_side_and_forwards_start_flag(
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"G28\nM84\n"
    sha = hashlib.sha256(payload).hexdigest()
    key = S3Storage.object_key(actor.workspace.id, sha, "gcode")
    storage.put(key, payload, "text/x-gcode")
    cleanup_keys.append(key)
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.derived,
        sha256=sha,
        storage_key=key,
        mime="text/x-gcode",
        format="gcode",
        byte_size=len(payload),
        units=Units.mm,
        created_by=actor.user.id,
    )
    db_session.add(asset)
    db_session.flush()
    settings = test_s3_settings(database_url).model_copy(
        update={
            "printer_bridge_provider": "octoprint",
            "octoprint_url": "http://printer.lan/",
            "octoprint_api_key": "server-secret",
        }
    )
    captured: dict[str, Any] = {}
    control_requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        if url.endswith("/api/job"):
            control_requests.append({"url": url, **kwargs})
            return httpx.Response(204, request=httpx.Request("POST", url))
        captured.update(url=url, **kwargs)
        return httpx.Response(
            201,
            json={"files": {"local": {"path": "jobs/owl.gcode"}}},
            request=httpx.Request("POST", url),
        )

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("/api/job"):
            return httpx.Response(
                200,
                json={
                    "state": "Printing",
                    "job": {"file": {"name": "owl.gcode"}},
                    "progress": {"completion": 37.5, "printTime": 120, "printTimeLeft": 300},
                },
                request=request,
            )
        if url.endswith("/api/printer"):
            return httpx.Response(
                200,
                json={
                    "state": {"flags": {"operational": True, "printing": True, "paused": False}},
                    "temperature": {
                        "tool0": {"actual": 208.2, "target": 210},
                        "bed": {"actual": 59.7, "target": 60},
                    },
                },
                request=request,
            )
        return httpx.Response(
            200, content=b"jpeg", headers={"content-type": "image/jpeg"}, request=request
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    result = printer_bridge.dispatch_gcode(
        db_session,
        storage,
        settings,
        user_id=actor.user.id,
        workspace_id=actor.workspace.id,
        asset_id=asset.id,
        start=True,
    )

    assert captured["url"] == "http://printer.lan/api/files/local"
    assert captured["headers"] == {"X-Api-Key": "server-secret"}
    assert captured["data"] == {"select": "true", "print": "true"}
    assert captured["files"]["file"][1] == payload
    assert result.remote_path == "jobs/owl.gcode" and result.printing is True
    live = printer_bridge.printer_state(settings)
    assert live.state == "Printing" and live.completion_pct == 37.5
    assert live.nozzle_actual_c == 208.2 and live.bed_target_c == 60
    for action, payload in (
        ("pause", {"command": "pause", "action": "pause"}),
        ("resume", {"command": "pause", "action": "resume"}),
        ("cancel", {"command": "cancel"}),
    ):
        controlled = printer_bridge.control_print(settings, action)
        assert controlled.state == "Printing"
        assert control_requests[-1]["url"] == "http://printer.lan/api/job"
        assert control_requests[-1]["headers"] == {"X-Api-Key": "server-secret"}
        assert control_requests[-1]["json"] == payload
    image, content_type = printer_bridge.camera_snapshot(settings)
    assert image == b"jpeg" and content_type == "image/jpeg"


def test_printer_live_state_and_camera_have_a_hardware_free_preview(
    api_client: TestClient, actor: Actor
) -> None:
    profile = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Preview printer",
        },
        headers=actor.headers,
    ).json()
    live = api_client.get(f"/api/v1/printer-profiles/{profile['id']}/live", headers=actor.headers)
    assert live.status_code == 200
    assert live.json()["state"] == "Ready · test mode"
    assert live.json()["operational"] is True and live.json()["provider"] == "stub"

    camera = api_client.get(
        f"/api/v1/printer-profiles/{profile['id']}/camera", headers=actor.headers
    )
    assert camera.status_code == 200
    assert camera.headers["content-type"].startswith("image/svg+xml")
    assert b"No real camera was contacted" in camera.content


def test_printer_control_is_editor_only_and_never_simulated(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    profile = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Controlled printer",
        },
        headers=actor.headers,
    ).json()
    viewer = make_actor(db_session, workspace=actor.workspace, role="viewer")

    blocked = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/live/control",
        json={"action": "pause"},
        headers=viewer.headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "forbidden"

    demo = api_client.post(
        f"/api/v1/printer-profiles/{profile['id']}/live/control",
        json={"action": "pause"},
        headers=actor.headers,
    )
    assert demo.status_code == 409
    assert demo.json()["error"]["code"] == "printer_bridge_control_unavailable"


# --- T-064 analyze-print ----------------------------------------------------------------------


def test_slice_preview_uses_model_geometry_and_printer_profile(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    box = trimesh.creation.box(extents=(20, 10, 4))
    data = box.export(file_type="stl")
    _, version, asset = seed_version(db_session, storage, actor, data)
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/slice-preview", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["type"] == "slice_preview"
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.result is not None
    assert job.result["total_layers"] == 20
    assert job.result["sampled_layers"][0]["paths"]
    assert job.result["preview_only"] is True


def test_slice_produces_a_downloadable_gcode_export(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    box = trimesh.creation.box(extents=(20, 10, 4))
    data = box.export(file_type="stl")
    _, version, asset = seed_version(db_session, storage, actor, data)
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/slice",
        json={
            "infill_density_pct": 100,
            "wall_count": 2,
            "top_solid_layers": 5,
            "bottom_solid_layers": 3,
            "adaptive_layer_height": True,
            "min_layer_height_mm": 0.1,
            "max_layer_height_mm": 0.3,
            "supports": True,
            "support_type": "tree",
            "support_modifiers": [
                {
                    "mode": "block",
                    "region": {
                        "kind": "box",
                        "min_mm": [1000, 1000, 1000],
                        "max_mm": [1010, 1010, 1010],
                    },
                }
            ],
            "process_modifiers": [
                {
                    "infill_density_pct": 70,
                    "print_speed_pct": 60,
                    "nozzle_temperature_offset_c": 10,
                    "infill_pattern": "honeycomb",
                    "wall_count": 3,
                    "region": {
                        "kind": "box",
                        "min_mm": [-10, -5, -2],
                        "max_mm": [0, 5, 2],
                    },
                }
            ],
            "adhesion_mode": "brim",
            "brim_width_mm": 6,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["type"] == "slice"
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.input["support_type"] == "tree"
    assert job.input["support_modifiers"][0]["mode"] == "block"
    assert job.input["process_modifiers"][0]["infill_density_pct"] == 70
    assert job.input["process_modifiers"][0]["print_speed_pct"] == 60
    assert job.input["process_modifiers"][0]["nozzle_temperature_offset_c"] == 10
    assert job.input["process_modifiers"][0]["infill_pattern"] == "honeycomb"
    assert job.input["process_modifiers"][0]["wall_count"] == 3
    assert job.input["top_solid_layers"] == 5
    assert job.input["bottom_solid_layers"] == 3
    assert job.input["adaptive_layer_height"] is True
    assert job.input["min_layer_height_mm"] == 0.1
    assert job.input["max_layer_height_mm"] == 0.3
    assert job.input["adhesion_mode"] == "brim"
    assert job.input["brim_width_mm"] == 6
    assert job.input["raft_base_density_pct"] == 40
    assert job.input["raft_interface_density_pct"] == 100
    assert job.input["raft_density_profiled"] is False
    assert job.result is not None
    stats = job.result["stats"]
    assert job.result["format"] == "gcode"
    assert 0 < stats["total_layers"] < 20
    assert stats["layer_height_mode"] == "adaptive"
    assert 0.1 <= stats["min_layer_height_mm"] <= stats["max_layer_height_mm"] <= 0.3
    assert stats["filament_used_mm"] > 0
    assert stats["support_modifiers"] == 1
    assert stats["process_modifiers"] == 1
    assert stats["process_modified_layers"] > 0
    assert stats["adhesion_mode"] == "brim"
    assert stats["brim_width_mm"] == 6
    assert stats["brim_loops"] > 0

    gcode_asset = db_session.get(Asset, uuid.UUID(job.result["asset_id"]))
    assert gcode_asset is not None and gcode_asset.format == "gcode"
    cleanup_keys.append(gcode_asset.storage_key)
    assert db_session.get(VersionAsset, (version.id, gcode_asset.id, AssetRole.export)) is not None

    download = api_client.get(f"/api/v1/assets/{gcode_asset.id}/download", headers=actor.headers)
    assert download.status_code == 200
    assert (
        download.json()["format"] == "gcode"
        and download.json()["byte_size"] == stats["gcode_bytes"]
    )

    gcode_text = storage.get(gcode_asset.storage_key).decode("utf-8")
    assert gcode_text.splitlines()[-1] == "M84"
    assert "M83" in gcode_text  # relative extrusion
    assert gcode_text.count("G28") == 1
    assert "support_type=tree" in gcode_text
    assert "support_modifiers=1" in gcode_text
    assert "process_modifiers=1" in gcode_text
    marker = "; TYPE:local-infill density=70% speed=60% temperature_offset=+10C pattern=honeycomb"
    assert marker in gcode_text
    assert "; TYPE:local-perimeter walls=3" in gcode_text
    assert "; TYPE:local-perimeter walls=3 speed=60%" in gcode_text
    assert "; TYPE:local-solid-infill speed=60%" in gcode_text
    local_section = gcode_text.split(marker, 1)[1]
    assert re.search(r"^G1 X[-0-9.]+ Y[-0-9.]+ E[0-9.]+ F3600$", local_section, re.MULTILINE)
    assert "M104 S210" in local_section
    assert "M104 S200" in local_section
    assert "top_layers=5 bottom_layers=3" in gcode_text
    assert "layer_height=adaptive" in gcode_text
    assert "; adhesion: mode=brim width=6mm" in gcode_text
    assert stats["solid_skin_paths"] > 0


def test_slice_rejects_an_unknown_support_type(
    api_client: TestClient,
    actor: Actor,
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json={"supports": True, "support_type": "lattice"},
        headers=actor.headers,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "process_modifiers",
    [
        [
            {
                "infill_density_pct": 50,
                "region": {
                    "kind": "lasso",
                    "axis": "x",
                    "offset_mm": 0,
                    "depth_mm": 10,
                    "points_mm": [[0, 0], [10, 0], [10, 10]],
                },
            }
        ],
        [
            {
                "infill_density_pct": 50,
                "infill_pattern": "gyroid",
                "region": {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
            }
        ],
        [
            {
                "infill_density_pct": 50,
                "region": {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
            }
        ]
        * 65,
        [
            {
                "infill_density_pct": 50,
                "print_speed_pct": 201,
                "region": {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
            }
        ],
        [
            {
                "infill_density_pct": 50,
                "wall_count": 7,
                "region": {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
            }
        ],
        [
            {
                "infill_density_pct": 50,
                "nozzle_temperature_offset_c": 21,
                "region": {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
            }
        ],
    ],
)
def test_slice_rejects_unsafe_process_modifiers(
    api_client: TestClient,
    actor: Actor,
    process_modifiers: list[dict[str, object]],
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json={"process_modifiers": process_modifiers},
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_slice_builds_real_mouse_ears_on_the_first_layer(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    data = trimesh.creation.box(extents=(20, 20, 4)).export(file_type="stl")
    _, version, asset = seed_version(db_session, storage, actor, data)
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/slice",
        json={
            "adhesion_mode": "mouse_ears",
            "mouse_ear_diameter_mm": 12,
            "mouse_ear_points_mm": [[-10, -10, 0]],
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.input["mouse_ear_diameter_mm"] == 12
    assert job.input["mouse_ear_points_mm"] == [[-10.0, -10.0, 0.0]]
    stats = (job.result or {})["stats"]
    assert stats["adhesion_mode"] == "mouse_ears"
    assert stats["mouse_ear_diameter_mm"] == 12
    assert stats["mouse_ear_count"] == 1
    assert stats["mouse_ear_requested_count"] == 1
    assert stats["mouse_ear_rejected_count"] == 0
    gcode_asset = db_session.get(Asset, uuid.UUID((job.result or {})["asset_id"]))
    assert gcode_asset is not None
    cleanup_keys.append(gcode_asset.storage_key)
    gcode_text = storage.get(gcode_asset.storage_key).decode("utf-8")
    assert "; adhesion: mode=mouse_ears diameter=12mm painted_points=1" in gcode_text
    assert "; TYPE:mouse-ear" in gcode_text


def test_slice_builds_a_profiled_raft_and_lifts_the_model(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    data = trimesh.creation.box(extents=(20, 20, 4)).export(file_type="stl")
    _, version, asset = seed_version(db_session, storage, actor, data)
    cleanup_keys.append(asset.storage_key)
    profile_response = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",
            "name": "Raft tuned",
            "default_material_id": "petg",
            "raft_density_profiles": {
                "petg": {"base_density_pct": 40, "interface_density_pct": 75}
            },
        },
        headers=actor.headers,
    )
    assert profile_response.status_code == 201, profile_response.text
    profile = profile_response.json()
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/slice",
        json={
            "adhesion_mode": "raft",
            "adhesion_speed_pct": 55,
            "raft_margin_mm": 7,
            "raft_base_layers": 2,
            "raft_interface_layers": 3,
            "raft_air_gap_mm": 0.25,
            "printer_profile_id": profile["id"],
            "material_id": "petg",
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.input["raft_margin_mm"] == 7
    assert job.input["adhesion_speed_pct"] == 55
    assert job.input["raft_base_layers"] == 2
    assert job.input["raft_interface_layers"] == 3
    assert job.input["raft_air_gap_mm"] == 0.25
    assert job.input["raft_base_density_pct"] == 40
    assert job.input["raft_interface_density_pct"] == 75
    assert job.input["raft_density_profiled"] is True
    stats = (job.result or {})["stats"]
    assert stats["adhesion_mode"] == "raft"
    assert stats["raft_layers"] == 5
    assert stats["raft_base_layers"] == 2
    assert stats["raft_interface_layers"] == 3
    assert stats["raft_margin_mm"] == 7
    assert stats["raft_air_gap_mm"] == 0.25
    assert stats["adhesion_speed_pct"] == 55
    assert stats["raft_base_density_pct"] == 40
    assert stats["raft_interface_density_pct"] == 75
    assert stats["raft_density_profiled"] is True
    gcode_asset = db_session.get(Asset, uuid.UUID((job.result or {})["asset_id"]))
    assert gcode_asset is not None
    cleanup_keys.append(gcode_asset.storage_key)
    gcode_text = storage.get(gcode_asset.storage_key).decode("utf-8")
    assert gcode_text.count("; TYPE:raft-base") == 2
    assert gcode_text.count("; TYPE:raft-interface") == 3
    assert (
        "; adhesion: mode=raft margin=7mm layers=5 base_layers=2 "
        "interface_layers=3 gap=0.25mm base_density=40% interface_density=75% "
        "density_source=profile speed=55%" in gcode_text
    )


@pytest.mark.parametrize(
    "body",
    [
        {"adhesion_mode": "brim", "brim_width_mm": 0},
        {"adhesion_mode": "brim", "brim_width_mm": 16},
        {"adhesion_mode": "mouse_ears", "mouse_ear_diameter_mm": 4},
        {"adhesion_mode": "mouse_ears", "mouse_ear_diameter_mm": 31},
        {"adhesion_mode": "brim", "mouse_ear_points_mm": [[0, 0, 0]]},
        {"adhesion_mode": "mouse_ears", "mouse_ear_points_mm": [[0, 0, 0]] * 33},
        {"adhesion_mode": "raft", "raft_margin_mm": 2},
        {"adhesion_mode": "raft", "raft_margin_mm": 16},
        {"adhesion_mode": "raft", "adhesion_speed_pct": 19},
        {"adhesion_mode": "raft", "adhesion_speed_pct": 101},
        {"adhesion_mode": "raft", "raft_base_layers": 0},
        {"adhesion_mode": "raft", "raft_interface_layers": 4},
        {"adhesion_mode": "raft", "raft_air_gap_mm": 0.04},
        {"adhesion_mode": "raft", "raft_air_gap_mm": 0.51},
    ],
)
def test_slice_rejects_unsafe_adhesion(
    api_client: TestClient,
    actor: Actor,
    body: dict[str, object],
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json=body,
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_slice_rejects_support_paint_when_supports_are_disabled(
    api_client: TestClient,
    actor: Actor,
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json={
            "supports": False,
            "support_modifiers": [
                {
                    "mode": "enforce",
                    "region": {
                        "kind": "box",
                        "min_mm": [0, 0, 0],
                        "max_mm": [10, 10, 10],
                    },
                }
            ],
        },
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_slice_rejects_invalid_solid_layer_counts(
    api_client: TestClient,
    actor: Actor,
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json={"top_solid_layers": 21, "bottom_solid_layers": -1},
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_slice_rejects_reversed_adaptive_layer_range(
    api_client: TestClient,
    actor: Actor,
) -> None:
    response = api_client.post(
        f"/api/v1/models/{uuid.uuid4()}/slice",
        json={
            "adaptive_layer_height": True,
            "min_layer_height_mm": 0.3,
            "max_layer_height_mm": 0.1,
        },
        headers=actor.headers,
    )
    assert response.status_code == 422


def test_analyze_print_stores_result(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, t_shape_stl())
    cleanup_keys.append(asset.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/analyze-print", json={}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["type"] == "analyze_print"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["kind"] == "analysis" and result["status"] in ("yellow", "green")
    report = result["report"]
    assert report["schema_version"] == 1 and report["material"]["name"] == "PLA"
    assert report["printer"]["name"] == "Generic 256 mm FDM"  # no profile -> defaults
    assert {w["code"] for w in report["warnings"]} >= {"overhangs"}
    assert report["metrics"]["support_volume_mm3"] == pytest.approx(12_000, rel=0.01)

    record = db_session.get(PrintAnalysisRecord, uuid.UUID(result["analysis_id"]))
    assert record is not None and record.job_id == job.id and record.material_id == "pla"
    listed = api_client.get(
        f"/api/v1/models/{version.id}/print-analyses", headers=actor.headers
    ).json()
    assert [a["id"] for a in listed] == [result["analysis_id"]]
    detail = api_client.get(
        f"/api/v1/print-analyses/{result['analysis_id']}", headers=actor.headers
    ).json()
    assert detail["report"]["summary"].startswith("Printability")


# --- T-071 / T-072 profile-aware analysis --------------------------------------------------------


def test_profile_and_material_change_the_result(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _, version, asset = seed_version(db_session, storage, actor, t_shape_stl())
    cleanup_keys.append(asset.storage_key)
    tiny = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "bambu-a1-mini",
            "name": "mini with wide nozzle",
            "nozzle_mm": "0.8",
            "max_overhang_deg": "60",
            "is_default": True,
        },
        headers=actor.headers,
    ).json()

    api_client.post(
        f"/api/v1/models/{version.id}/analyze-print",
        json={"material_id": "abs"},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["report"]
    assert report["printer"]["name"].startswith("Bambu Lab A1 mini")
    assert report["printer"]["bed_x_mm"] == 180 and report["printer"]["nozzle_mm"] == 0.8
    assert report["printer"]["max_overhang_deg"] == 60
    assert report["material"]["name"] == "ABS" and report["material"]["density_g_cm3"] == 1.04
    assert report["metrics"]["mass_g"] == pytest.approx(5500 / 1000 * 1.04, rel=1e-3)
    record = db_session.get(PrintAnalysisRecord, uuid.UUID((job.result or {})["analysis_id"]))
    assert record is not None and record.printer_profile_id == uuid.UUID(tiny["id"])
    assert record.material_id == "abs"


# --- T-067 optimize-print ---------------------------------------------------------------------


def test_optimize_print_recommends_without_changing_the_model(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(db_session, storage, actor, t_shape_stl())
    cleanup_keys.append(asset.storage_key)
    api_client.post(f"/api/v1/models/{version.id}/optimize-print", json={}, headers=actor.headers)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result: dict[str, Any] = job.result or {}
    assert result["kind"] == "optimize" and result["applied"] is False
    assert result["recommended_orientation"]["label"] == "upside down"
    assert len(result["report"]["candidates"]) >= 6
    versions = api_client.get(
        f"/api/v1/projects/{project.id}/versions", headers=actor.headers
    ).json()
    assert len(versions) == 1  # non-destructive


def test_optimize_print_apply_creates_rotated_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, asset = seed_version(db_session, storage, actor, t_shape_stl())
    cleanup_keys.append(asset.storage_key)
    api_client.post(
        f"/api/v1/models/{version.id}/optimize-print",
        json={"apply": True},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["applied"] is True
    new_version = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert new_version is not None and new_version.parent_version_id == version.id
    assert new_version.provenance["orientation"]["label"] == "upside down"
    new_asset = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert new_asset is not None
    cleanup_keys.append(new_asset.storage_key)
    mesh = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(new_asset.storage_key)),
        file_type="stl",
        force="mesh",
    )
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.volume == pytest.approx(5500, rel=1e-3)
    # Upside down: the wide bar is now on the bed -> full-width contact at z=0.
    assert np.asarray(mesh.bounds[0]).tolist() == pytest.approx([0, 0, 0])
    assert mesh.extents[0] == pytest.approx(50)
    head = api_client.get(f"/api/v1/projects/{project.id}", headers=actor.headers).json()
    assert head["head_version_id"] == result["version_id"]


def test_analyze_requires_mesh_and_membership(
    api_client: TestClient, db_session: Session, storage: S3Storage, cleanup_keys: list[str]
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    project = projects.create_project(
        db_session, user_id=owner.user.id, workspace_id=owner.workspace.id, name="empty"
    )
    empty = projects.create_version(db_session, user_id=owner.user.id, project_id=project.id)
    assert (
        api_client.post(f"/api/v1/models/{empty.id}/analyze-print", json={}, headers=owner.headers)
    ).status_code == 422
    _, version, asset = seed_version(db_session, storage, owner, t_shape_stl())
    cleanup_keys.append(asset.storage_key)
    assert (
        api_client.post(
            f"/api/v1/models/{version.id}/analyze-print", json={}, headers=stranger.headers
        )
    ).status_code == 404
