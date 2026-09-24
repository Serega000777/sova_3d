"""E15 (F-014/F-015): bring any model in, take any format out, and say what it cost."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.formats import exportable
from app.jobs import runner
from app.models import Asset, ProjectVersion
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


def upload(
    api_client: TestClient, actor: Actor, data: bytes, filename: str, content_type: str
) -> str:
    """The client's own path: presign, PUT, complete."""
    created = api_client.post(
        "/api/v1/uploads",
        json={
            "workspace_id": str(actor.workspace.id),
            "filename": filename,
            "content_type": content_type,
            "byte_size": len(data),
        },
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    presigned = created.json()
    import urllib.request

    request = urllib.request.Request(
        presigned["url"], data=data, method="PUT", headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        assert response.status in (200, 204)

    completed = api_client.post(
        "/api/v1/assets/complete",
        json={"upload_id": presigned["upload_id"], "sha256": hashlib.sha256(data).hexdigest()},
        headers=actor.headers,
    )
    assert completed.status_code == 201, completed.text
    asset_id: str = completed.json()["id"]
    return asset_id


def box_bytes(file_type: str) -> bytes:
    mesh = trimesh.creation.box(extents=(30, 20, 10))
    exported = mesh.export(file_type=file_type)
    return exported if isinstance(exported, bytes) else str(exported).encode()


def run_all(db: Session, storage: S3Storage) -> list[Any]:
    done = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


@pytest.fixture
def project(api_client: TestClient, actor: Actor) -> str:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "imported"},
        headers=actor.headers,
    ).json()["id"]
    return project_id


# --- T-110 -----------------------------------------------------------------------------------


def test_an_uploaded_obj_becomes_a_version_with_the_original_kept(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,
) -> None:
    """What Blender exports goes in; what the viewport renders comes out — both are kept."""
    asset_id = upload(api_client, actor, box_bytes("obj"), "from-blender.obj", "model/obj")

    accepted = api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["source_format"] == "obj"

    version = db_session.get(ProjectVersion, result["version_id"])
    assert version is not None
    roles = {link.role: link.asset_id for link in version.assets}
    assert roles[AssetRole.source] == Asset.__table__.c.id.type.python_type(asset_id)
    model = db_session.get(Asset, roles[AssetRole.model])
    assert model is not None and model.format == "stl"  # the viewport always gets a mesh
    assert version.label == "from-blender.obj"
    assert version.provenance["operation"] == "import_model"
    # F-015: the conversion is reported, not assumed.
    assert version.provenance["integrity"]["status"] in ("pass", "warn")


def test_an_uploaded_dae_declares_its_own_unit_and_becomes_a_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,
) -> None:
    """COLLADA carries a real <asset><unit>, unlike OBJ/STL/PLY — centimetres here."""
    mesh = trimesh.creation.box(extents=(30, 20, 10))
    data = mesh.export(file_type="dae")
    data = data if isinstance(data, bytes) else str(data).encode()
    data = data.replace(b"</asset>", b'<unit meter="0.01" name="centimeter"/></asset>')
    asset_id = upload(api_client, actor, data, "part.dae", "model/vnd.collada+xml")

    accepted = api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["source_format"] == "dae"

    version = db_session.get(ProjectVersion, result["version_id"])
    assert version is not None
    model = db_session.get(
        Asset, {link.role: link.asset_id for link in version.assets}[AssetRole.model]
    )
    assert model is not None and model.format == "stl"
    mesh_out = trimesh.load(
        io.BytesIO(storage.get(model.storage_key)), file_type="stl", force="mesh"
    )
    assert tuple(round(s, 1) for s in mesh_out.extents) == (300.0, 200.0, 100.0)  # cm -> mm


def test_an_uploaded_stl_needs_no_conversion(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,
) -> None:
    asset_id = upload(api_client, actor, box_bytes("stl"), "part.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": asset_id, "label": "Part"},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version = db_session.get(ProjectVersion, (job.result or {})["version_id"])
    assert version is not None
    roles = {link.role for link in version.assets}
    assert roles == {AssetRole.model}  # nothing to keep a copy of
    assert version.label == "Part"


def test_importing_someone_elses_file_is_a_404(
    api_client: TestClient, actor: Actor, db_session: Session, project: str
) -> None:
    stranger = make_actor(db_session)
    theirs = upload(api_client, stranger, box_bytes("stl"), "theirs.stl", "model/stl")
    response = api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": theirs},
        headers=actor.headers,
    )
    assert response.status_code == 404


# --- T-112 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["glb", "3mf", "obj", "ply", "dae", "usdz"])
def test_convert_an_uploaded_model_to_another_format(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    target: str,
) -> None:
    asset_id = upload(api_client, actor, box_bytes("stl"), "part.stl", "model/stl")
    accepted = api_client.post(
        f"/api/v1/assets/{asset_id}/convert", json={"format": target}, headers=actor.headers
    )
    assert accepted.status_code == 202, accepted.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["format"] == target and result["byte_size"] > 0
    assert result["integrity"]["status"] in ("pass", "warn")

    converted = db_session.get(Asset, result["asset_id"])
    assert converted is not None and converted.format == target

    # And it is downloadable, which is the whole point.
    download = api_client.get(f"/api/v1/assets/{converted.id}/download", headers=actor.headers)
    assert download.status_code == 200 and download.json()["url"]


def test_converting_to_a_format_we_cannot_write_is_refused(
    api_client: TestClient, actor: Actor
) -> None:
    asset_id = upload(api_client, actor, box_bytes("stl"), "part.stl", "model/stl")
    response = api_client.post(
        f"/api/v1/assets/{asset_id}/convert", json={"format": "gltf"}, headers=actor.headers
    )
    assert response.status_code == 415
    assert "supported" in response.json()["error"]["details"]
    # CAD formats are writable (F-078), but not from a mesh: the answer says where they come from
    response = api_client.post(
        f"/api/v1/assets/{asset_id}/convert", json={"format": "iges"}, headers=actor.headers
    )
    assert response.status_code == 422
    assert "B-Rep" in response.json()["error"]["message"]


def test_converting_to_the_same_format_is_refused(api_client: TestClient, actor: Actor) -> None:
    asset_id = upload(api_client, actor, box_bytes("stl"), "part.stl", "model/stl")
    response = api_client.post(
        f"/api/v1/assets/{asset_id}/convert", json={"format": "stl"}, headers=actor.headers
    )
    assert response.status_code == 422


def test_the_registry_and_the_exporter_agree_on_what_can_be_written() -> None:
    """A format the API offers but the worker cannot write would fail only at run time."""
    from worker import exporters

    from app.formats import Representation

    meshes = {spec.id for spec in exportable() if spec.representation is not Representation.brep}
    assert meshes == set(exporters.SUPPORTED_TARGETS)
    # CAD formats are written by the kernel, not the mesh exporter (F-078)
    assert {spec.id for spec in exportable() if spec.representation is Representation.brep} == {
        "step",
        "iges",
    }


def test_a_cad_upload_is_read_by_the_kernel(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,
) -> None:
    """STEP is B-Rep, not a mesh: the kernel reads it and the platform stores the mesh."""
    from worker import geometry

    fixture = Path(__file__).resolve().parents[3] / "worker" / "tests" / "fixtures" / "box.step"
    if not geometry.available() or not fixture.exists():
        pytest.skip("geometry-service binary or STEP fixture missing")

    asset_id = upload(api_client, actor, fixture.read_bytes(), "part.step", "model/step")
    api_client.post(
        f"/api/v1/projects/{project}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version = db_session.get(ProjectVersion, (job.result or {})["version_id"])
    assert version is not None
    model = db_session.get(
        Asset, {link.role: link.asset_id for link in version.assets}[AssetRole.model]
    )
    assert model is not None and model.format == "stl"
