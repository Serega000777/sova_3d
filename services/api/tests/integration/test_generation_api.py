"""F-001/F-075: a description becomes a mesh version; off unless the server enables it."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import generate_mesh

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import Job, JobArtifact, JobStatus
from app.models.generation import ThreeDGeneration
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
        json={"prompt": "  an owl\nfigurine ", "size_mm": 70, "quality": "quality"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "generate_mesh"
    queued = db_session.get(Job, uuid.UUID(response.json()["job_id"]))
    assert queued is not None and queued.timeout_seconds == 4200

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    head = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()[
        "head_version"
    ]
    assert head["label"] == "an owl figurine"
    provenance = head["provenance"]
    assert provenance["operation"] == "generate_mesh" and provenance["size_mm"] == 70
    assert provenance["quality"] == "quality" and provenance["sampling_steps"] == 32
    assert (
        provenance["prompt"] == "an owl figurine" and "not a dimensioned part" in provenance["note"]
    )
    assert provenance["repair"].get("ok") is not False


def test_provider_neutral_generation_estimates_runs_and_reports_quality(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(api_client)
    monkeypatch.setattr(generate_mesh, "run_shap_e", _fake_shap_e)
    body = {
        "mode": "text",
        "purpose": "draft",
        "prompt": "an owl figurine",
        "target_format": "stl",
        "size_mm": 70,
        "quality": "quality",
    }

    providers = api_client.get("/api/v1/3d-generation/providers", headers=actor.headers)
    assert providers.status_code == 200, providers.text
    assert providers.json()[0] == {
        "provider": "shap_e",
        "model": "text300M",
        "version": "50131012",
        "modes": ["text"],
        "purposes": ["draft", "standard"],
        "formats": ["stl"],
        "max_images": 0,
        "supports_pbr": False,
        "supports_rigging": False,
        "supports_target_triangles": False,
        "self_hosted": True,
    }
    estimate = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json=body,
        headers=actor.headers,
    )
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["credits"] == "30" and estimate.json()["cost_usd"] is None

    accepted = api_client.post(
        f"/api/v1/projects/{project}/3d-generations",
        json=body,
        headers={**actor.headers, "Idempotency-Key": "provider-neutral-owl"},
    )
    assert accepted.status_code == 202, accepted.text
    job_id = uuid.UUID(accepted.json()["job_id"])
    record = db_session.get(ThreeDGeneration, job_id)
    assert record is not None
    assert record.provider == "shap_e" and record.provider_model == "text300M"
    assert record.request["purpose"] == "draft" and record.estimate["credits"] == "30"

    repeated = api_client.post(
        f"/api/v1/projects/{project}/3d-generations",
        json=body,
        headers={**actor.headers, "Idempotency-Key": "provider-neutral-owl"},
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["job_id"] == str(job_id)
    conflicting = api_client.post(
        f"/api/v1/projects/{project}/3d-generations",
        json={**body, "prompt": "a different figurine"},
        headers={**actor.headers, "Idempotency-Key": "provider-neutral-owl"},
    )
    assert conflicting.status_code == 409, conflicting.text

    queued = api_client.get(f"/api/v1/3d-generations/{job_id}", headers=actor.headers)
    assert queued.status_code == 200 and queued.json()["status"] == "queued"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    ready = api_client.get(f"/api/v1/3d-generations/{job_id}", headers=actor.headers)
    assert ready.status_code == 200, ready.text
    payload = ready.json()
    assert payload["status"] == "ready"
    assert payload["raw_asset_id"] and payload["normalized_asset_id"]
    assert payload["quality_report"]["import_ok"] is True
    assert payload["quality_report"]["triangles"] > 0
    roles = {
        artifact.role
        for artifact in db_session.query(JobArtifact).filter(JobArtifact.job_id == job_id)
    }
    assert roles == {"raw_model", "model"}


def test_provider_neutral_generation_rejects_unsupported_marketing_claims(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    _enable(api_client)
    response = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={
            "mode": "text",
            "purpose": "game",
            "prompt": "a hero",
            "target_format": "glb",
            "target_triangles": 20_000,
            "pbr": True,
        },
        headers=actor.headers,
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert set(error["details"]["unsupported"]) == {
        "purpose=game",
        "target_format=glb",
        "pbr=true",
        "target_triangles",
    }


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
    neutral_denied = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={
            "mode": "text",
            "purpose": "draft",
            "prompt": "a vase",
            "target_format": "stl",
        },
        headers=viewer.headers,
    )
    assert neutral_denied.status_code == 403, neutral_denied.text
    for body in (
        {"prompt": ""},
        {"prompt": "a vase", "size_mm": 2},
        {"prompt": "x" * 301},
        {"prompt": "a vase", "quality": "turbo"},
    ):
        refused = api_client.post(
            f"/api/v1/projects/{project}/generate-mesh", json=body, headers=actor.headers
        )
        assert refused.status_code == 422, body
