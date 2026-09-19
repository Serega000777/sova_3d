"""E28 (F-007): "make it lighter" — a hollow preview with the mass before and after."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def test_lightening_is_a_preview_with_the_mass_before(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Box 80x60x40 mm with 2 holes for M4", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    version_id = str((built.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/models/{version_id}/optimize",
        json={"goal": "lighter", "material_id": "pla", "language": "ru"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    started = response.json()
    assert started["job"]["type"] == "manual_edit"
    report = started["report"]
    assert report["wall_mm"] == 1.8 and report["opening"] == "bottom"
    assert report["density_g_cm3"] == 1.24
    assert report["mass_before_g"] > 0
    assert any("Полость" in change for change in report["changes"])
    kinds = [op["type"] for op in report["operations"]]
    assert kinds[0] == "shell" and kinds.count("create_cylinder") == 2  # a boss per hole

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["preview"] is True
    from worker import geometry as kernel

    if kernel.available():  # the real kernel: the hollow part holds less material
        before = (built.result or {})["bodies"][-1]["volume_mm3"]
        after = result["bodies"][-1]["volume_mm3"]
        assert after < before * 0.6
    kept = api_client.post(
        f"/api/v1/versions/{result['version_id']}/finalize", headers=actor.headers
    )
    assert kept.status_code == 200 and kept.json()["label"] == "Облегчено"


def test_a_thin_part_cannot_be_hollowed_and_says_why(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Box 80x60x6 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    (built,) = run_all(db_session, storage)
    version_id = str((built.result or {})["version_id"])
    refused = api_client.post(
        f"/api/v1/models/{version_id}/optimize", json={"goal": "lighter"}, headers=actor.headers
    )
    assert refused.status_code == 422
    assert "left solid" in refused.json()["error"]["message"]


def test_the_sentence_hollows_the_current_model(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Box 80x60x40 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "сделай её легче", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    plan = (job.result or {})["plan"]
    assert [op["type"] for op in plan["operations"]][-1] == "shell"
    assert any("Полость" in a for a in plan["assumptions"])
