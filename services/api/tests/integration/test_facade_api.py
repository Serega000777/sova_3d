"""A compatible house-box version becomes an exact, immutable facade version."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker.facade_materials import FacadeMaterialResult

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.engineering.facade import MAX_OPENINGS, FacadeRequest
from app.models import ProjectVersion
from app.models.core import WorkspaceRole
from app.models.execution import Job, JobStatus, Operation
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401
from tests.integration.test_imports_api import run_all, upload
from tests.integration.test_scanner_api import start_scanner_session, stl


def house_box(
    api_client: TestClient,
    actor: Actor,
    db: Session,
    storage: S3Storage,
    shape: str = "rectangle",
) -> str:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 10_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": shape,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def rectangular_house(api_client: TestClient, actor: Actor, db: Session, storage: S3Storage) -> str:
    return house_box(api_client, actor, db, storage)


def window(index: int) -> dict[str, Any]:
    return {
        "kind": "window",
        "side": ("front", "back", "left", "right")[index % 4],
        "center_mm": 1_000 + (index // 4) * 150,
        "width_mm": 300,
        "height_mm": 600,
    }


def facade_jobs(db: Session) -> list[Job]:
    return db.query(Job).filter(Job.type == "edit_facade").all()


def refusal(response: Any) -> dict[str, Any]:
    assert response.status_code == 422, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == "validation_failed"
    return error


def test_facade_editor_creates_child_with_opening_schedule_and_roof(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    accepted = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={
            "wall_thickness_mm": 250,
            "roof": "gable",
            "roof_height_mm": 1_400,
            "overhang_mm": 350,
            "openings": [
                {
                    "kind": "door",
                    "side": "front",
                    "center_mm": 2_000,
                    "width_mm": 900,
                    "height_mm": 2_100,
                },
                {
                    "kind": "window",
                    "side": "right",
                    "center_mm": 4_000,
                    "width_mm": 1_200,
                    "height_mm": 1_400,
                    "sill_mm": 900,
                },
            ],
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["type"] == "edit_facade"
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and str(made.parent_version_id) == source_id
    assert made.provenance["facade"]["request"]["roof"] == "gable"
    assert len(made.provenance["facade"]["request"]["openings"]) == 2
    assert result["opening_count"] == 2
    operations = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == made.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [operation.operation_type for operation in operations] == [
        "create_box",
        "shell",
        "create_box",
        "boolean",
        "create_box",
        "boolean",
        "extrude",
        "boolean",
    ]
    door, kept_window = made.provenance["facade"]["request"]["openings"]
    assert door["sill_mm"] == 0 and kept_window["sill_mm"] == 900
    # the persisted door sill is the one the cutter used: 2 mm below the floor
    assert operations[2].params["origin_mm"][2] == door["sill_mm"] - 2
    assert operations[4].params["origin_mm"][2] == kept_window["sill_mm"]

    # a facade version traces back to its rectangular house box, so it can be edited again
    again = api_client.post(
        f"/api/v1/models/{made.id}/facade", json={"roof": "flat"}, headers=actor.headers
    )
    assert again.status_code == 202, again.text
    (second_job,) = run_all(db_session, storage)
    assert second_job.status is JobStatus.succeeded, second_job.error
    second_version_id = (second_job.result or {})["version_id"]
    third = api_client.post(
        f"/api/v1/models/{second_version_id}/facade",
        json={"roof": "none"},
        headers=actor.headers,
    )
    assert third.status_code == 202, third.text


def test_facade_materials_carry_by_surface_key_and_drop_removed_opening(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_materials(source: Any, request: Any, output: Any) -> FacadeMaterialResult:
        output.write_bytes(b"glTF-material-preview")
        return FacadeMaterialResult(
            ok=True,
            faces=24,
            assigned_faces=8,
            applied_surface_keys=[item.surface_key for item in request.assignments],
        )

    monkeypatch.setattr("app.jobs.facade.run_in_sandbox", fake_materials)
    source_id = rectangular_house(api_client, actor, db_session, storage)
    openings = [
        {
            "opening_id": "window-kept",
            "kind": "window",
            "side": "front",
            "center_mm": 2_000,
            "width_mm": 1_200,
            "height_mm": 1_400,
            "sill_mm": 900,
        },
        {
            "opening_id": "window-removed",
            "kind": "window",
            "side": "front",
            "center_mm": 5_000,
            "width_mm": 1_200,
            "height_mm": 1_400,
            "sill_mm": 900,
        },
    ]
    first = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={
            "roof": "none",
            "openings": openings,
            "surface_assignments": [
                {"surface_key": "wall.front", "colour": "#aa5522"},
                {"surface_key": "opening.window-kept.left", "colour": "#eeeeee"},
                {"surface_key": "opening.window-removed.left", "colour": "#333333"},
            ],
        },
        headers=actor.headers,
    )
    assert first.status_code == 202, first.text
    (first_job,) = run_all(db_session, storage)
    assert first_job.status is JobStatus.succeeded, first_job.error
    first_version_id = str((first_job.result or {})["version_id"])

    # Omit assignments deliberately: the server carries matching semantic roles from the
    # trusted producing job, while the removed opening's key is reported and never retargeted.
    second = api_client.post(
        f"/api/v1/models/{first_version_id}/facade",
        json={"roof": "none", "openings": openings[:1]},
        headers=actor.headers,
    )
    assert second.status_code == 202, second.text
    (second_job,) = run_all(db_session, storage)
    assert second_job.status is JobStatus.succeeded, second_job.error
    made = db_session.get(ProjectVersion, uuid.UUID(str((second_job.result or {})["version_id"])))
    assert made is not None
    assignments = made.provenance["facade"]["request"]["surface_assignments"]
    assert {item["surface_key"] for item in assignments} == {
        "wall.front",
        "opening.window-kept.left",
    }
    report = made.provenance["facade"]["material_report"]
    assert report["dropped_surface_keys"] == ["opening.window-removed.left"]
    assert "opening.window-removed.left" not in report["applied_surface_keys"]
    preview = next(link for link in made.assets if link.role is AssetRole.preview)
    assert storage.get(preview.asset.storage_key).startswith(b"glTF")


def test_facade_editor_rejects_incompatible_versions_and_non_editors(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    url = f"/api/v1/models/{source_id}/facade"
    stranger = make_actor(db_session)
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    assert api_client.post(url, json={}, headers=stranger.headers).status_code == 404
    assert api_client.post(url, json={}, headers=viewer.headers).status_code == 403

    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "not a house"},
        headers=actor.headers,
    ).json()["id"]
    incompatible = api_client.post(
        f"/api/v1/projects/{project_id}/versions", json={}, headers=actor.headers
    ).json()["id"]
    refused = api_client.post(
        f"/api/v1/models/{incompatible}/facade", json={}, headers=actor.headers
    )
    assert refused.status_code == 422
    assert "rectangular house-box" in refused.text


@pytest.mark.parametrize("shape", ["l_shape", "t_shape"])
def test_facade_editor_rejects_non_rectangular_house_boxes(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    shape: str,
) -> None:
    source_id = house_box(api_client, actor, db_session, storage, shape=shape)
    error = refusal(
        api_client.post(f"/api/v1/models/{source_id}/facade", json={}, headers=actor.headers)
    )
    assert error["details"]["reason"] == "not_rectangular"
    assert f"this house is {shape}" in error["message"]
    assert facade_jobs(db_session) == []


def test_facade_editor_rejects_scanned_versions(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "scanned house"},
        headers=actor.headers,
    ).json()["id"]
    scan = start_scanner_session(api_client, actor, project_id=project_id)
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
            },
            headers=actor.headers,
        )
        assert added.status_code == 201, added.text
    finalized = api_client.post(
        f"/api/v1/scans/{scan['id']}/finalize", json={}, headers=actor.headers
    )
    assert finalized.status_code == 202, finalized.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    kept = api_client.post(
        f"/api/v1/scans/{scan['id']}/accept", json={"label": "Scan"}, headers=actor.headers
    )
    assert kept.status_code == 200, kept.text
    scanned_id = kept.json()["result_version_id"]

    error = refusal(
        api_client.post(f"/api/v1/models/{scanned_id}/facade", json={}, headers=actor.headers)
    )
    assert error["details"]["reason"] == "not_house_box"
    assert "scanned" in error["message"]
    assert facade_jobs(db_session) == []


def test_facade_editor_ignores_forged_rectangular_provenance(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    real_id = rectangular_house(api_client, actor, db_session, storage)
    real = db_session.get(ProjectVersion, uuid.UUID(real_id))
    assert real is not None
    house = {
        "length_mm": 10_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    # copies a genuine house-box job id and claims both facade and house-box ancestry
    forged = api_client.post(
        f"/api/v1/projects/{real.project_id}/versions",
        json={
            "parent_version_id": real_id,
            "provenance": {
                "operation": "edit_facade",
                "job_id": real.provenance["job_id"],
                "house_box": {"request": house},
                "facade": {"house": house, "source_version_id": real_id},
            },
        },
        headers=actor.headers,
    )
    assert forged.status_code == 201, forged.text
    error = refusal(
        api_client.post(
            f"/api/v1/models/{forged.json()['id']}/facade", json={}, headers=actor.headers
        )
    )
    assert error["details"]["reason"] == "not_house_box"
    assert facade_jobs(db_session) == []


def test_facade_editor_accepts_the_opening_ceiling_and_rejects_one_more(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert MAX_OPENINGS == 126
    source_id = rectangular_house(api_client, actor, db_session, storage)
    url = f"/api/v1/models/{source_id}/facade"

    def no_plan(_: FacadeRequest) -> None:
        raise AssertionError("the API must never construct the worker plan")

    monkeypatch.setattr(FacadeRequest, "build", no_plan)
    too_many = [window(index) for index in range(MAX_OPENINGS + 1)]
    error = refusal(
        api_client.post(url, json={"roof": "gable", "openings": too_many}, headers=actor.headers)
    )
    (detail,) = error["details"]
    assert detail["loc"][-1] == "openings" and detail["type"] == "too_long"
    assert facade_jobs(db_session) == []

    accepted = api_client.post(
        url,
        json={"roof": "gable", "openings": too_many[:MAX_OPENINGS]},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = facade_jobs(db_session)
    assert len(job.input["request"]["openings"]) == MAX_OPENINGS


def test_facade_editor_rejects_raised_doors(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    door = {"kind": "door", "side": "front", "center_mm": 2_000, "width_mm": 900}
    error = refusal(
        api_client.post(
            f"/api/v1/models/{source_id}/facade",
            json={"openings": [{**door, "height_mm": 2_100, "sill_mm": 300}]},
            headers=actor.headers,
        )
    )
    assert "doors start at floor level" in error["message"]
    assert facade_jobs(db_session) == []

    accepted = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={"openings": [{**door, "height_mm": 2_100, "sill_mm": 0}]},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = facade_jobs(db_session)
    assert job.input["request"]["openings"][0]["sill_mm"] == 0
