"""E27 (F-081): a model too big for the bed becomes parts that print — by request or by
the sentence "разрежь на 3 части"."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def build(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project_id: str,
    prompt: str,
) -> str:
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": prompt, "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def test_cut_into_three_parts_with_dowels_as_a_version_of_parts(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = build(api_client, actor, db_session, storage, project, "Box 300x40x30 mm")
    response = api_client.post(
        f"/api/v1/models/{version_id}/split",
        json={"parts": 3, "label": "Три части"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "split_model"
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert [p["name"] for p in result["parts"]] == ["part_01", "part_02", "part_03"]
    assert all(p["dowel_holes"] == 2 for p in result["parts"])
    assert len(result["dowels"]) == 4
    assert result["warnings"] == [] and result["repaired"] is False

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["label"] == "Три части" and version["state"] == "finalized"
    split = version["provenance"]["split"]
    assert [plane["axis"] for plane in split["planes"]] == ["x", "x"]  # the longest extent
    # every part is a downloadable STL of its own, on its biggest flat face at the origin
    for part in split["parts"]:
        download = api_client.get(
            f"/api/v1/assets/{part['asset_id']}/download", headers=actor.headers
        )
        assert download.status_code in (200, 307), download.text
        assert part["extents_mm"] == [100.0, 40.0, 30.0]  # 300 / 3, lying on its 100 x 40 side
    # the plate with everything laid out is what the clients render
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["head_version"]["id"] == result["version_id"]


def test_fit_the_printer_needs_a_profile_and_uses_its_bed(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = build(api_client, actor, db_session, storage, project, "Box 400x50x30 mm")
    refused = api_client.post(
        f"/api/v1/models/{version_id}/split", json={"fit_bed": True}, headers=actor.headers
    )
    assert refused.status_code == 422
    assert "Printers page" in refused.json()["error"]["message"]

    created = api_client.post(
        "/api/v1/printer-profiles",
        json={
            "workspace_id": str(actor.workspace.id),
            "printer_model_id": "prusa-mini",  # 180 x 180 x 180
            "name": "Desk MINI",
            "is_default": True,
        },
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    accepted = api_client.post(
        f"/api/v1/models/{version_id}/split",
        json={"fit_bed": True, "connectors": {"kind": "none"}},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    # 400 mm into 3 parts under 170 mm of room; every part fits, no dowels asked for
    assert len(result["parts"]) == 3 and all(p["fits_bed"] for p in result["parts"])
    assert result["dowels"] == []
    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["provenance"]["split"]["request"]["bed"] == {
        "x_mm": 180.0,
        "y_mm": 180.0,
        "z_mm": 180.0,
    }


def test_the_sentence_cuts_the_current_model(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project, "Box 200x40x30 mm")
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Разрежь пополам без штифтов", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.type == "split_model"
    result = job.result or {}
    assert len(result["parts"]) == 2 and result["dowels"] == []
    request = api_client.get(
        f"/api/v1/ai-requests/{accepted['ai_request_id']}", headers=actor.headers
    ).json()
    assert request["status"] == "executed"
    assert request["result_version_id"] == result["version_id"]
    version = api_client.get(f"/api/v1/versions/{result['version_id']}", headers=actor.headers)
    assert version.json()["label"] == "Разрежь пополам без штифтов"


def test_a_project_without_a_model_cannot_be_cut(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    # the sentence with nothing to cut goes to the planner, which asks for sizes
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "cut it in half", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202
    assert response.json()["job_id"]
    missing = api_client.post(
        "/api/v1/models/00000000-0000-0000-0000-000000000000/split",
        json={"parts": 2},
        headers=actor.headers,
    )
    assert missing.status_code == 404
