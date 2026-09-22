"""T-064/T-067 analyze/optimize-print jobs; T-068..T-072 catalogue, profiles and
profile-aware analysis."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from typing import Any

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
from app.models.versioning import AssetKind, AssetRole
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


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
            "is_default": True,
        },
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["is_default"] and float(profile["nozzle_mm"]) == 0.6
    assert float(profile["layer_height_mm"]) == 0.2  # default

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
