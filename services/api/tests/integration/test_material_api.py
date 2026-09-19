"""E25 (F-009): "print it in TPU" — the part adapts, as a preview you keep or discard."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401


def test_adapting_an_organizer_for_tpu_is_a_preview_with_a_report(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={
            "prompt": "Organizer 120x80x40 mm with 4 compartments, 2 holes for M4",
            "units": "mm",
            "target": "print",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    version_id = str((built.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/models/{version_id}/adapt-material",
        json={"material_id": "tpu", "language": "ru"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    started = response.json()
    assert started["job"]["type"] == "manual_edit"
    report = started["report"]
    assert report["material_id"] == "tpu" and report["wall_mm"] == 2.25
    assert any("Стенки и дно" in change for change in report["changes"])
    kinds = {op["parameter"] for op in report["operations"] if op["type"] == "set_parameter"}
    assert {"origin_x_mm", "origin_y_mm", "origin_z_mm", "width_mm", "diameter_mm"} <= kinds

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["preview"] is True  # a draft until the user keeps it
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["head_version"]["id"] == version_id
    from worker import geometry as kernel

    if kernel.available():  # the real kernel: thicker walls leave more material
        before = (built.result or {})["bodies"][-1]["volume_mm3"]
        after = result["bodies"][-1]["volume_mm3"]
        assert after > before
    kept = api_client.post(
        f"/api/v1/versions/{result['version_id']}/finalize", headers=actor.headers
    )
    assert kept.status_code == 200
    assert kept.json()["label"] == "Под TPU 95A"


def test_a_part_without_a_plan_cannot_be_adapted_but_the_engineer_can_advise(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    import trimesh

    mesh = trimesh.creation.box(extents=(30, 20, 10))
    exported = mesh.export(file_type="stl")
    stl = exported if isinstance(exported, bytes) else str(exported).encode()
    asset_id = upload(api_client, actor, stl, "box.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{project}/imports", json={"asset_id": asset_id}, headers=actor.headers
    )
    (job,) = run_all(db_session, storage)
    version_id = str((job.result or {})["version_id"])
    refused = api_client.post(
        f"/api/v1/models/{version_id}/adapt-material",
        json={"material_id": "tpu"},
        headers=actor.headers,
    )
    assert refused.status_code == 422
    assert "engineering" in refused.json()["error"]["details"]["hint"]


def test_an_unknown_material_is_refused(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Box 40x20x8 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    (built,) = run_all(db_session, storage)
    version_id = str((built.result or {})["version_id"])
    refused = api_client.post(
        f"/api/v1/models/{version_id}/adapt-material",
        json={"material_id": "unobtainium"},
        headers=actor.headers,
    )
    assert refused.status_code == 422
