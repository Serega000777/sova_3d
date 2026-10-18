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
                    "floor": 2,
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
    assert door["sill_mm"] == 0
    assert kept_window["sill_mm"] == 900 and kept_window["floor"] == 2
    # the persisted door sill is the one the cutter used: 2 mm below the floor
    assert operations[2].params["origin_mm"][2] == door["sill_mm"] - 2
    assert operations[4].params["origin_mm"][2] == 3_000 + kept_window["sill_mm"]

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


def test_facade_editor_creates_immutable_shed_roof_with_one_material_surface(
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
            "roof": "shed",
            "roof_height_mm": 1_200,
            "overhang_mm": 300,
            "surface_assignments": [{"surface_key": "roof.slope", "colour": "#b65f28"}],
        },
        headers=actor.headers,
    )

    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and str(made.parent_version_id) == source_id
    facade = made.provenance["facade"]
    assert facade["request"]["roof"] == "shed"
    assert facade["surfaces"][-1] == {
        "key": "roof.slope",
        "kind": "roof",
        "side": "single",
    }
    assert facade["material_report"]["applied_surface_keys"] == ["roof.slope"]


def test_facade_editor_persists_mirrored_duplicate_and_unfilled_opening(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    openings = [
        {
            "opening_id": "front-window",
            "kind": "window",
            "side": "front",
            "center_mm": 2_000,
            "width_mm": 1_200,
            "height_mm": 1_400,
            "sill_mm": 900,
        },
        {
            "opening_id": "front-window-copy",
            "kind": "opening",
            "side": "front",
            "center_mm": 8_000,
            "width_mm": 1_200,
            "height_mm": 1_400,
            "sill_mm": 900,
        },
    ]
    accepted = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={"roof": "none", "openings": openings},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    made = db_session.get(ProjectVersion, uuid.UUID(str((job.result or {})["version_id"])))
    assert made is not None
    persisted = made.provenance["facade"]["request"]["openings"]
    assert persisted == openings
    assert made.parent_version_id == uuid.UUID(source_id)


def test_facade_editor_rejects_unknown_opening_kind_before_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    jobs_before = len(facade_jobs(db_session))
    rejected = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={"openings": [{**window(0), "kind": "arch"}]},
        headers=actor.headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert len(facade_jobs(db_session)) == jobs_before


def test_facade_command_proposes_named_overhang_before_enqueuing_and_applies_exactly(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    made = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={
            "roof": "gable",
            "overhang_mm": 200,
            "openings": [window(0)],
        },
        headers=actor.headers,
    )
    assert made.status_code == 202, made.text
    (first_job,) = run_all(db_session, storage)
    assert first_job.status is JobStatus.succeeded, first_job.error
    facade_id = str((first_job.result or {})["version_id"])
    jobs_before = len(facade_jobs(db_session))

    proposed = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-proposal",
        json={"prompt": "Увеличь свес крыши до 40 см"},
        headers=actor.headers,
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json() == {
        "source_version_id": facade_id,
        "parameter": "roof_overhang",
        "label_ru": "Свес крыши",
        "label_en": "Roof overhang",
        "current_value_mm": 200.0,
        "new_value_mm": 400.0,
        "unit": "mm",
    }
    assert len(facade_jobs(db_session)) == jobs_before
    english = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-proposal",
        json={"prompt": "Set roof overhang to .4 m"},
        headers=actor.headers,
    )
    assert english.status_code == 200, english.text
    assert english.json()["new_value_mm"] == 400
    assert len(facade_jobs(db_session)) == jobs_before

    tampered = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-apply",
        json={
            "prompt": "Увеличь свес крыши до 40 см",
            "expected_current_mm": 200,
            "proposed_new_mm": 500,
        },
        headers=actor.headers,
    )
    assert refusal(tampered)["message"] == "the proposal target does not match the command"
    assert len(facade_jobs(db_session)) == jobs_before

    applied = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-apply",
        json={
            "prompt": "Увеличь свес крыши до 40 см",
            "expected_current_mm": 200,
            "proposed_new_mm": 400,
        },
        headers=actor.headers,
    )
    assert applied.status_code == 202, applied.text
    queued = facade_jobs(db_session)[-1]
    assert queued.input["request"]["overhang_mm"] == 400
    assert queued.input["request"]["openings"] == first_job.input["request"]["openings"]
    (finished,) = run_all(db_session, storage)
    assert finished.status is JobStatus.succeeded, finished.error
    version = db_session.get(ProjectVersion, uuid.UUID(str((finished.result or {})["version_id"])))
    assert version is not None
    assert version.provenance["facade"]["request"]["overhang_mm"] == 400


def test_facade_command_proposes_wall_thickness_before_enqueuing_and_applies_exactly(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    made = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={
            "wall_thickness_mm": 250,
            "roof": "flat",
            "overhang_mm": 350,
            "openings": [window(0)],
        },
        headers=actor.headers,
    )
    assert made.status_code == 202, made.text
    (first_job,) = run_all(db_session, storage)
    assert first_job.status is JobStatus.succeeded, first_job.error
    facade_id = str((first_job.result or {})["version_id"])
    jobs_before = len(facade_jobs(db_session))

    proposed = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-proposal",
        json={"prompt": "Измени толщину стен до 300 мм"},
        headers=actor.headers,
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json() == {
        "source_version_id": facade_id,
        "parameter": "wall_thickness",
        "label_ru": "Толщина стен",
        "label_en": "Wall thickness",
        "current_value_mm": 250.0,
        "new_value_mm": 300.0,
        "unit": "mm",
    }
    assert len(facade_jobs(db_session)) == jobs_before
    for prompt in ("Set wall thickness to .3 m", "Установи толщину стены на 30 см"):
        equivalent = api_client.post(
            f"/api/v1/models/{facade_id}/facade-command-proposal",
            json={"prompt": prompt},
            headers=actor.headers,
        )
        assert equivalent.status_code == 200, equivalent.text
        assert equivalent.json()["new_value_mm"] == 300
        assert len(facade_jobs(db_session)) == jobs_before

    stale = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-apply",
        json={
            "prompt": "Измени толщину стен до 300 мм",
            "expected_current_mm": 200,
            "proposed_new_mm": 300,
        },
        headers=actor.headers,
    )
    assert (
        refusal(stale)["message"] == "the proposal current value does not match its source version"
    )
    assert len(facade_jobs(db_session)) == jobs_before

    tampered = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-apply",
        json={
            "prompt": "Измени толщину стен до 300 мм",
            "expected_current_mm": 250,
            "proposed_new_mm": 350,
        },
        headers=actor.headers,
    )
    assert refusal(tampered)["message"] == "the proposal target does not match the command"
    assert len(facade_jobs(db_session)) == jobs_before

    applied = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-apply",
        json={
            "prompt": "Измени толщину стен до 300 мм",
            "expected_current_mm": 250,
            "proposed_new_mm": 300,
        },
        headers=actor.headers,
    )
    assert applied.status_code == 202, applied.text
    queued = facade_jobs(db_session)[-1]
    assert queued.input["request"]["wall_thickness_mm"] == 300
    assert queued.input["request"]["overhang_mm"] == 350
    assert queued.input["request"]["openings"] == first_job.input["request"]["openings"]
    (finished,) = run_all(db_session, storage)
    assert finished.status is JobStatus.succeeded, finished.error
    version = db_session.get(ProjectVersion, uuid.UUID(str((finished.result or {})["version_id"])))
    assert version is not None
    assert version.provenance["facade"]["request"]["wall_thickness_mm"] == 300


@pytest.mark.parametrize(
    ("prompt", "message"),
    [
        ("Измени толщину стен до 250 мм", "wall thickness is already set to this value"),
        (
            "увеличь толщину стен на 50 мм",
            "only an explicit wall-thickness target is supported here",
        ),
        ("Set wall thickness to 99 mm", "wall thickness must be between 100 and 600 mm"),
        ("Set wall thickness to 601 mm", "wall thickness must be between 100 and 600 mm"),
    ],
)
def test_facade_wall_thickness_command_rejects_noop_relative_and_out_of_bounds_without_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    prompt: str,
    message: str,
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    made = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={"wall_thickness_mm": 250, "roof": "none"},
        headers=actor.headers,
    )
    assert made.status_code == 202, made.text
    (first_job,) = run_all(db_session, storage)
    facade_id = str((first_job.result or {})["version_id"])
    jobs_before = len(facade_jobs(db_session))

    rejected = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-proposal",
        json={"prompt": prompt},
        headers=actor.headers,
    )
    assert refusal(rejected)["message"] == message
    assert len(facade_jobs(db_session)) == jobs_before


def test_facade_wall_thickness_command_requires_saved_facade_version_without_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    jobs_before = len(facade_jobs(db_session))

    rejected = api_client.post(
        f"/api/v1/models/{source_id}/facade-command-proposal",
        json={"prompt": "Измени толщину стен до 300 мм"},
        headers=actor.headers,
    )
    assert refusal(rejected)["message"] == "this version is not a saved facade variant"
    rejected_apply = api_client.post(
        f"/api/v1/models/{source_id}/facade-command-apply",
        json={
            "prompt": "Измени толщину стен до 300 мм",
            "expected_current_mm": 250,
            "proposed_new_mm": 300,
        },
        headers=actor.headers,
    )
    assert refusal(rejected_apply)["message"] == "this version is not a saved facade variant"
    assert len(facade_jobs(db_session)) == jobs_before


@pytest.mark.parametrize(
    "prompt",
    [
        "increase roof overhang by 200 mm",
        "увеличь свес крыши на 200 мм",
        "удали крышу",
    ],
)
def test_facade_command_rejects_ambiguous_or_unsupported_text_without_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    prompt: str,
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    made = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={"roof": "flat", "overhang_mm": 200},
        headers=actor.headers,
    )
    assert made.status_code == 202, made.text
    (first_job,) = run_all(db_session, storage)
    facade_id = str((first_job.result or {})["version_id"])
    jobs_before = len(facade_jobs(db_session))

    response = api_client.post(
        f"/api/v1/models/{facade_id}/facade-command-proposal",
        json={"prompt": prompt},
        headers=actor.headers,
    )
    assert response.status_code == 422, response.text
    assert len(facade_jobs(db_session)) == jobs_before


def test_facade_materials_carry_by_surface_key_and_drop_removed_opening(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_materials(source: Any, request: Any, output: Any) -> FacadeMaterialResult:
        addressed = next(item for item in request.openings if item.opening_id == "window-kept")
        assert addressed.sill_mm == 3_900
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
            "floor": 2,
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


def test_named_facade_variant_lists_estimate_and_applies_only_to_matching_surfaces(
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
    source = db_session.get(ProjectVersion, uuid.UUID(source_id))
    assert source is not None
    project_id = str(source.project_id)
    openings = [
        {
            "opening_id": "right-window",
            "kind": "window",
            "side": "right",
            "center_mm": 4_000,
            "width_mm": 1_200,
            "height_mm": 1_400,
            "sill_mm": 900,
        }
    ]
    named = api_client.post(
        f"/api/v1/models/{source_id}/facade",
        json={
            "variant_name": "Warm brick",
            "roof": "flat",
            "openings": openings,
            "surface_assignments": [
                {
                    "surface_key": "wall.front",
                    "colour": "#aa5522",
                    "unit_price_per_m2": 25,
                    "currency": "USD",
                    "price_source_url": "https://supplier.example/warm-brick",
                }
            ],
        },
        headers=actor.headers,
    )
    assert named.status_code == 202, named.text
    (named_job,) = run_all(db_session, storage)
    assert named_job.status is JobStatus.succeeded, named_job.error
    named_version_id = str((named_job.result or {})["version_id"])
    named_version = db_session.get(ProjectVersion, uuid.UUID(named_version_id))
    assert named_version is not None
    assert named_version.label == "Facade variant: Warm brick"
    assert named_version.provenance["facade"]["variant_name"] == "Warm brick"

    listed = api_client.get(f"/api/v1/projects/{project_id}/facade-variants", headers=actor.headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    variant = listed.json()[0]
    assert variant["version_id"] == named_version_id
    assert variant["name"] == "Warm brick"
    assert variant["category_areas_m2"] == pytest.approx(
        {"walls": 214.32, "roof": 91.16, "opening_frames": 1.3}
    )
    assert variant["assigned_area_m2"] == pytest.approx(60)
    assert variant["estimated_cost"] == pytest.approx(1_500)
    assert variant["currency"] == "USD"
    assert variant["surface_assignments"][0]["price_source_url"].startswith("https://")

    target = api_client.post(
        f"/api/v1/models/{named_version_id}/facade",
        json={
            "roof": "flat",
            "openings": openings,
            "surface_assignments": [{"surface_key": "wall.front", "colour": "#eeeeee"}],
        },
        headers=actor.headers,
    )
    assert target.status_code == 202, target.text
    (target_job,) = run_all(db_session, storage)
    target_version_id = str((target_job.result or {})["version_id"])
    applied = api_client.post(
        f"/api/v1/models/{target_version_id}/facade-variant",
        json={"variant_version_id": named_version_id},
        headers=actor.headers,
    )
    assert applied.status_code == 202, applied.text
    (applied_job,) = run_all(db_session, storage)
    assert applied_job.status is JobStatus.succeeded, applied_job.error
    applied_version = db_session.get(
        ProjectVersion, uuid.UUID(str((applied_job.result or {})["version_id"]))
    )
    assert applied_version is not None
    assert str(applied_version.parent_version_id) == target_version_id
    facade = applied_version.provenance["facade"]
    assert facade["request"]["surface_assignments"][0]["colour"] == "#aa5522"
    assert facade["applied_variant"] == {
        "name": "Warm brick",
        "version_id": named_version_id,
    }
    assert applied_version.label == "Applied facade variant: Warm brick"
    # Applying a variant does not create a duplicate catalogue entry.
    listed_again = api_client.get(
        f"/api/v1/projects/{project_id}/facade-variants", headers=actor.headers
    )
    assert len(listed_again.json()) == 1

    mismatched = api_client.post(
        f"/api/v1/models/{target_version_id}/facade",
        json={"roof": "flat", "openings": [], "surface_assignments": []},
        headers=actor.headers,
    )
    assert mismatched.status_code == 202, mismatched.text
    (mismatched_job,) = run_all(db_session, storage)
    mismatched_version_id = str((mismatched_job.result or {})["version_id"])
    rejected = api_client.post(
        f"/api/v1/models/{mismatched_version_id}/facade-variant",
        json={"variant_version_id": named_version_id},
        headers=actor.headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["details"]["reason"] == "surface_set_mismatch"

    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    assert (
        api_client.get(
            f"/api/v1/projects/{project_id}/facade-variants", headers=viewer.headers
        ).status_code
        == 200
    )
    assert (
        api_client.post(
            f"/api/v1/models/{target_version_id}/facade-variant",
            json={"variant_version_id": named_version_id},
            headers=viewer.headers,
        ).status_code
        == 403
    )


def test_facade_variant_name_and_price_inputs_fail_closed_before_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    url = f"/api/v1/models/{source_id}/facade"
    blank = api_client.post(url, json={"variant_name": "   "}, headers=actor.headers)
    assert blank.status_code == 422
    partial_price = api_client.post(
        url,
        json={
            "surface_assignments": [
                {
                    "surface_key": "wall.front",
                    "colour": "#ffffff",
                    "unit_price_per_m2": 10,
                    "currency": "USD",
                }
            ]
        },
        headers=actor.headers,
    )
    assert partial_price.status_code == 422
    insecure_source = api_client.post(
        url,
        json={
            "surface_assignments": [
                {
                    "surface_key": "wall.front",
                    "colour": "#ffffff",
                    "unit_price_per_m2": 10,
                    "currency": "USD",
                    "price_source_url": "http://supplier.example/wall",
                }
            ]
        },
        headers=actor.headers,
    )
    assert insecure_source.status_code == 422
    assert facade_jobs(db_session) == []


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


def test_facade_editor_rejects_stair_house_instead_of_dropping_floor_bodies(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    kernel_or_fake: None,  # noqa: F811
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "rectangle",
            "stair": {"step_count": 17},
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    source_id = str((job.result or {})["version_id"])

    error = refusal(
        api_client.post(f"/api/v1/models/{source_id}/facade", json={}, headers=actor.headers)
    )
    assert error["details"]["reason"] == "multi_floor_stair_not_supported"
    assert "does not yet preserve separate floor" in error["message"]
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
