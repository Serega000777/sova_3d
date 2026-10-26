"""E21 (F-027): two parts put together, a verdict, and a fix the edit endpoint accepts."""

from __future__ import annotations

from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.core import WorkspaceRole
from app.models.engineering import FitTestRecord
from app.models.execution import Job, JobStatus
from app.models.versioning import AssetRole, ProjectVersion
from app.services.fit import advise
from app.storage import S3Storage
from tests.integration.conftest import Actor, alembic_config, make_actor, table_names
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401


def uploaded(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    name: str,
    stl: bytes,
) -> str:
    """A project whose head version is the uploaded mesh; returns the version id."""
    created = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": name},
        headers=actor.headers,
    ).json()
    asset_id = upload(api_client, actor, stl, f"{name}.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{created['id']}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def stl(mesh: Any) -> bytes:
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else str(exported).encode()


def test_migration_0012_adds_the_fit_tests_table(migrated_db: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0011")
    assert "fit_tests" not in table_names(migrated_db)
    command.upgrade(cfg, "head")
    assert "fit_tests" in table_names(migrated_db)


def test_a_fat_peg_collides_and_a_thin_one_slides(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    import trimesh

    block = trimesh.creation.box(extents=(30, 30, 10))
    block.apply_translation([15, 15, 5])
    hole = trimesh.creation.cylinder(radius=5.0, height=12)
    hole.apply_translation([15, 15, 5])
    host = uploaded(api_client, actor, db_session, storage, "block", stl(block.difference(hole)))
    fat = uploaded(
        api_client, actor, db_session, storage, "fat-peg", stl(trimesh.creation.cylinder(5.2, 20))
    )
    thin = uploaded(
        api_client, actor, db_session, storage, "thin-peg", stl(trimesh.creation.cylinder(4.85, 20))
    )

    response = api_client.post(
        "/api/v1/fit-tests",
        json={"version_a_id": host, "version_b_id": fat, "wanted": "sliding", "language": "ru"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["verdict"] == "collides"
    advice = result["report"]["advice"]
    assert advice["summary"].startswith("Не подходит")
    assert advice["numbers"]["target_diameter_mm"] == 10.7  # Ø10.4 + 0.3 sliding
    assert advice["fix"] is None  # an uploaded block has no plan to edit
    record = db_session.get(FitTestRecord, result["fit_test_id"])
    assert record is not None and record.verdict == "collides"

    api_client.post(
        "/api/v1/fit-tests",
        json={"version_a_id": host, "version_b_id": thin, "wanted": "sliding"},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["verdict"] == "sliding"
    assert result["report"]["advice"]["recommendation"] is None  # it is what was wanted

    listing = api_client.get(f"/api/v1/models/{host}/fit-tests", headers=actor.headers)
    # one transaction in tests means one timestamp, so the order is not asserted here
    assert sorted(row["verdict"] for row in listing.json()) == ["collides", "sliding"]


def test_a_measured_pose_becomes_one_idempotent_immutable_assembly(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    import trimesh

    a = uploaded(
        api_client,
        actor,
        db_session,
        storage,
        "assembly-a",
        stl(trimesh.creation.box((20, 20, 20))),
    )
    b = uploaded(
        api_client,
        actor,
        db_session,
        storage,
        "assembly-b",
        stl(trimesh.creation.box((10, 10, 10))),
    )

    api_client.post(
        "/api/v1/fit-tests",
        json={"version_a_id": a, "version_b_id": b, "auto_place": True},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    fit_test_id = result["fit_test_id"]
    measured = result["report"]["measured"]
    assert measured["verdict"] != "collides" and measured["b_transform"]

    made = api_client.post(
        f"/api/v1/fit-tests/{fit_test_id}/assembly",
        json={"label": "Measured bracket assembly"},
        headers=actor.headers,
    )
    assert made.status_code == 201, made.text
    scene = made.json()
    assert scene["parent_version_id"] == a
    nodes = {node["id"]: node for node in scene["nodes"]}
    assert set(nodes) == {"assembly", "part_a", "part_b"}
    assert nodes["part_b"]["world_transform"] == measured["b_transform"]
    assert nodes["part_a"]["resolved_asset_id"] != nodes["part_b"]["resolved_asset_id"]
    stored = db_session.get(ProjectVersion, scene["version_id"])
    assert stored is not None
    assert stored.provenance["fit_assembly"]["fit_test_id"] == fit_test_id
    assert len([link for link in stored.assets if link.role is AssetRole.model]) == 2

    repeated = api_client.post(
        f"/api/v1/fit-tests/{fit_test_id}/assembly",
        json={"label": "Ignored retry label"},
        headers=actor.headers,
    )
    assert repeated.status_code == 201
    assert repeated.json()["version_id"] == scene["version_id"]

    api_client.post(
        "/api/v1/fit-tests",
        json={"version_a_id": a, "version_b_id": b},
        headers=actor.headers,
    )
    (colliding_job,) = run_all(db_session, storage)
    assert colliding_job.status is JobStatus.succeeded
    colliding_result = colliding_job.result or {}
    assert colliding_result["verdict"] == "collides"
    refused = api_client.post(
        f"/api/v1/fit-tests/{colliding_result['fit_test_id']}/assembly",
        json={},
        headers=actor.headers,
    )
    assert refused.status_code == 422
    assert "colliding" in refused.json()["error"]["message"]


def test_a_created_fastener_targets_one_exact_top_hole(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    catalogue = api_client.get("/api/v1/fasteners", headers=actor.headers)
    assert catalogue.status_code == 200
    assert {item["size"] for item in catalogue.json()} >= {"M2", "M3", "M8"}

    made = api_client.post(
        "/api/v1/fasteners",
        json={
            "workspace_id": str(actor.workspace.id),
            "size": "M3",
            "length_mm": 12,
            "head": "socket_cap",
            "drive": "hex",
        },
        headers=actor.headers,
    )
    assert made.status_code == 202, made.text
    assert made.json()["fastener"]["thread_geometry"] == "smooth_nominal_envelope"
    (fastener_job,) = run_all(db_session, storage)
    assert fastener_job.status is JobStatus.succeeded, fastener_job.error
    fastener_version_id = str((fastener_job.result or {})["version_id"])
    fastener_version = db_session.get(ProjectVersion, fastener_version_id)
    assert fastener_version is not None
    assert fastener_version.provenance["fastener"]["size"] == "M3"
    assert fastener_version.provenance["fastener"]["drive_recess_modeled"] is False

    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    forbidden = api_client.post(
        "/api/v1/fasteners",
        json={"workspace_id": str(actor.workspace.id), "size": "M3", "length_mm": 12},
        headers=viewer.headers,
    )
    assert forbidden.status_code == 403

    requested = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 40x40x8 mm with a 3.4 mm hole", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert requested.status_code == 202, requested.text
    (plate_job,) = run_all(db_session, storage)
    assert plate_job.status is JobStatus.succeeded, plate_job.error
    plate_version_id = str((plate_job.result or {})["version_id"])

    fitted = api_client.post(
        f"/api/v1/models/{plate_version_id}/fastener-fits",
        json={
            "fastener_version_id": fastener_version_id,
            "hole_operation_id": "hole_1",
            "wanted": "clearance",
            "language": "ru",
        },
        headers=actor.headers,
    )
    assert fitted.status_code == 202, fitted.text
    fit_job = db_session.get(Job, fitted.json()["job_id"])
    assert fit_job is not None
    assert fit_job.input["auto_place"] is False
    assert fit_job.input["fastener_fit"]["hole_operation_id"] == "hole_1"
    assert fit_job.input["fastener_fit"]["head_seat_mm"][2] > 0

    stranger = make_actor(db_session)
    hidden = api_client.post(
        f"/api/v1/models/{plate_version_id}/fastener-fits",
        json={
            "fastener_version_id": fastener_version_id,
            "hole_operation_id": "hole_1",
        },
        headers=stranger.headers,
    )
    assert hidden.status_code == 404

    (measured,) = run_all(db_session, storage)
    assert measured.status is JobStatus.succeeded, measured.error
    report = (measured.result or {})["report"]
    assert report["fastener"]["hole_diameter_mm"] == 3.4
    assert report["fastener"]["radial_clearance_mm"] == pytest.approx(0.2)
    assert report["fastener"]["engagement_mm"] == 8
    assert report["fastener"]["limitations"]

    fit_record = db_session.get(FitTestRecord, (measured.result or {})["fit_test_id"])
    assert fit_record is not None
    if not report["fastener"]["geometry_compatible"]:
        refused = api_client.post(
            f"/api/v1/fit-tests/{fit_record.id}/assembly", json={}, headers=actor.headers
        )
        assert refused.status_code == 422
        # The local fake kernel deliberately does not drill the plate. Preserve that proof,
        # then exercise the same already-measured transform through the compatible branch.
        fit_record.verdict = "sliding"
        fit_record.report = {
            **fit_record.report,
            "fastener": {**fit_record.report["fastener"], "geometry_compatible": True},
        }
        db_session.flush()
    installed = api_client.post(
        f"/api/v1/fit-tests/{fit_record.id}/assembly", json={}, headers=actor.headers
    )
    assert installed.status_code == 201, installed.text
    nodes = {node["id"]: node for node in installed.json()["nodes"]}
    assert "fastener" in nodes and "part_b" not in nodes
    installed_version = db_session.get(ProjectVersion, installed.json()["version_id"])
    assert installed_version is not None
    assert installed_version.provenance["fit_assembly"]["fastener"]["size"] == "M3"


def test_the_fix_targets_the_opening_in_a_planned_part(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    import trimesh

    # part A from the kernel: a plate with a 10 mm hole in its plan
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 40x40x8 mm with a 10 mm hole", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    plate = str((built.result or {})["version_id"])
    peg = uploaded(
        api_client, actor, db_session, storage, "peg", stl(trimesh.creation.cylinder(5.2, 20))
    )
    api_client.post(
        "/api/v1/fit-tests",
        json={"version_a_id": plate, "version_b_id": peg, "wanted": "sliding"},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    advice = (job.result or {})["report"]["advice"]
    from worker import geometry as kernel

    if kernel.available():  # the fake kernel does not drill, so the peg meets a solid plate
        fix = advice["fix"]
        assert fix is not None
        assert fix["operations"] == [
            {
                "type": "set_parameter",
                "operation": "hole_1",
                "parameter": "diameter_mm",
                "value": 10.7,
            }
        ]
        applied = api_client.post(
            f"/api/v1/models/{plate}/edits",
            json={"operations": fix["operations"], "label": fix["label"]},
            headers=actor.headers,
        )
        assert applied.status_code == 202, applied.text
        (edited,) = run_all(db_session, storage)
        assert edited.status is JobStatus.succeeded, edited.error


def test_advice_words_for_every_verdict() -> None:
    plan = [
        {"id": "body", "type": "create_box", "width_mm": 40, "depth_mm": 40, "height_mm": 8},
        {
            "id": "hole_1",
            "type": "add_hole",
            "target": "body",
            "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            "position_mm": [20, 20],
            "diameter_mm": 10,
        },
    ]
    peg_box = [[14.8, 14.8, -5], [25.2, 25.2, 15]]  # a Ø10.4 peg
    collides = advise(
        {"verdict": "collides", "max_penetration_mm": 0.2, "interference_mm3": 64.1},
        operations_a=plan,
        b_bbox_mm=peg_box,
        wanted="sliding",
        material_id="pla",
        language="en",
    )
    assert collides.fix is not None and collides.fix["operations"][0]["value"] == 10.7
    assert "Ø10.7" in (collides.recommendation or "")
    press = advise(
        {"verdict": "press", "max_penetration_mm": 0.0, "min_clearance_mm": 0.02},
        operations_a=plan,
        b_bbox_mm=peg_box,
        wanted="sliding",
        material_id="pla",
        language="ru",
    )
    assert press.summary.startswith("Собирается") and "посадка с натягом" in press.summary
    assert press.numbers["change_diameter_mm"] == 0.26  # to the sliding allowance
    apart = advise(
        {"verdict": "apart", "max_penetration_mm": 0.0, "min_clearance_mm": 30},
        operations_a=plan,
        b_bbox_mm=None,
        wanted="sliding",
        material_id=None,
        language="en",
    )
    assert "do not meet" in apart.summary
