"""F-001/F-075: a description becomes a mesh version; off unless the server enables it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import generate_mesh

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def _enable(api_client: TestClient, provider: str = "shap_e") -> None:
    settings = api_client.app.state.settings  # type: ignore[attr-defined]
    api_client.app.state.settings = settings.model_copy(  # type: ignore[attr-defined]
        update={"mesh_generation_provider": provider}
    )


def _fake_shap_e(
    mode: str, source: str, out_dir: Path, **_: Any
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    assert mode == "text"
    raw = trimesh.creation.icosphere(subdivisions=2, radius=0.7)
    raw.apply_translation((1.0, -2.0, 0.3))
    return raw, {"vertices": len(raw.vertices), "faces": len(raw.faces)}


def test_generation_is_off_by_default(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    from app.config import Settings

    assert Settings.model_fields["mesh_generation_provider"].default == "none"
    _enable(api_client, "none")  # whatever the local .env says, the shipped default is off
    response = api_client.post(
        f"/api/v1/projects/{project}/generate-mesh",
        json={"prompt": "an owl figurine"},
        headers=actor.headers,
    )
    assert response.status_code == 501, response.text
    assert response.json()["error"]["code"] == "mesh_generation_not_enabled"


def test_a_description_becomes_a_repaired_mesh_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(api_client)
    monkeypatch.setattr(generate_mesh, "run_shap_e", _fake_shap_e)
    response = api_client.post(
        f"/api/v1/projects/{project}/generate-mesh",
        json={"prompt": "  an owl\nfigurine ", "size_mm": 70},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "generate_mesh"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    head = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()[
        "head_version"
    ]
    assert head["label"] == "an owl figurine"
    provenance = head["provenance"]
    assert provenance["operation"] == "generate_mesh" and provenance["size_mm"] == 70
    assert (
        provenance["prompt"] == "an owl figurine" and "not a dimensioned part" in provenance["note"]
    )
    assert provenance["repair"].get("ok") is not False


def test_a_viewer_cannot_generate_into_a_project_and_bad_input_is_refused(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    project: str,  # noqa: F811
) -> None:
    from app.models.core import WorkspaceRole
    from tests.integration.conftest import make_actor

    _enable(api_client)
    viewer = make_actor(db_session, WorkspaceRole.viewer, workspace=actor.workspace)
    denied = api_client.post(
        f"/api/v1/projects/{project}/generate-mesh",
        json={"prompt": "a vase"},
        headers=viewer.headers,
    )
    assert denied.status_code == 403, denied.text
    for body in ({"prompt": ""}, {"prompt": "a vase", "size_mm": 2}, {"prompt": "x" * 301}):
        refused = api_client.post(
            f"/api/v1/projects/{project}/generate-mesh", json=body, headers=actor.headers
        )
        assert refused.status_code == 422, body
