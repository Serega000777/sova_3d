"""F-001/F-075: a description becomes a mesh version; off unless the server enables it."""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session
from worker import generate_mesh

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import Job, JobArtifact, JobStatus
from app.models.generation import ThreeDGeneration
from app.models.versioning import Asset, AssetRole, ProjectVersion
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401


def _enable(api_client: TestClient, provider: str = "shap_e") -> None:
    settings = api_client.app.state.settings  # type: ignore[attr-defined]
    api_client.app.state.settings = settings.model_copy(  # type: ignore[attr-defined]
        update={"mesh_generation_provider": provider}
    )


def _fake_shap_e(
    mode: str, source: str, out_dir: Path, **_: Any
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    assert mode in {"text", "image"}
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
        "target_format": "glb",
        "size_mm": 70,
        "quality": "quality",
    }

    providers = api_client.get("/api/v1/3d-generation/providers", headers=actor.headers)
    assert providers.status_code == 200, providers.text
    assert providers.json()[0] == {
        "provider": "shap_e",
        "model": "text300M/image300M",
        "version": "50131012",
        "modes": ["text", "image"],
        "purposes": ["draft", "standard"],
        "formats": ["stl", "glb"],
        "max_images": 1,
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
    normalized = db_session.get(Asset, uuid.UUID(payload["normalized_asset_id"]))
    assert normalized is not None and normalized.format == "glb"
    assert payload["result"]["integrity"]["status"] in {"pass", "warn"}
    roles = {
        artifact.role
        for artifact in db_session.query(JobArtifact).filter(JobArtifact.job_id == job_id)
    }
    assert roles == {"raw_model", "model"}


def test_single_image_generation_keeps_source_lineage_and_multiview_is_not_faked(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.integration.conftest import make_actor

    _enable(api_client)
    monkeypatch.setattr(generate_mesh, "run_shap_e", _fake_shap_e)

    def image_bytes(colour: tuple[int, int, int]) -> bytes:
        stream = BytesIO()
        Image.new("RGB", (32, 32), colour).save(stream, format="PNG")
        return stream.getvalue()

    front_id = upload(api_client, actor, image_bytes((220, 40, 40)), "front.png", "image/png")
    back_id = upload(api_client, actor, image_bytes((40, 40, 220)), "back.png", "image/png")
    body = {
        "mode": "image",
        "purpose": "draft",
        "images": [{"asset_id": front_id, "view": "front"}],
        "target_format": "glb",
        "size_mm": 85,
    }

    accepted = api_client.post(
        f"/api/v1/projects/{project}/3d-generations",
        json=body,
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    generation = db_session.get(ThreeDGeneration, job.id)
    assert generation is not None and generation.provider_model == "image300M"
    result = job.result or {}
    version = db_session.get(ProjectVersion, uuid.UUID(str(result["version_id"])))
    assert version is not None
    roles = {link.role: link.asset_id for link in version.assets}
    assert roles[AssetRole.source] == uuid.UUID(front_id)
    model = db_session.get(Asset, roles[AssetRole.model])
    assert model is not None and model.format == "glb"
    assert version.provenance["mode"] == "image"
    assert version.provenance["source_asset_ids"] == [front_id]
    assert "hidden surfaces are inferred" in result["warnings"][0]

    multiview = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={
            "mode": "multiview",
            "purpose": "draft",
            "images": [
                {"asset_id": front_id, "view": "front"},
                {"asset_id": back_id, "view": "back"},
            ],
            "target_format": "glb",
        },
        headers=actor.headers,
    )
    assert multiview.status_code == 422, multiview.text
    assert multiview.json()["error"]["details"]["unsupported"] == ["mode=multiview"]

    stranger = make_actor(db_session)
    foreign_id = upload(
        api_client, stranger, image_bytes((40, 220, 40)), "foreign.png", "image/png"
    )
    foreign = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={**body, "images": [{"asset_id": foreign_id}]},
        headers=actor.headers,
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["error"]["code"] == "not_found"


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
        "pbr=true",
        "target_triangles",
    }


def test_provider_router_enforces_latency_and_unknown_cost_budget(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    _enable(api_client)
    body = {
        "mode": "text",
        "purpose": "draft",
        "prompt": "an owl figurine",
        "target_format": "glb",
    }

    latency = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={**body, "max_latency_seconds": 30},
        headers=actor.headers,
    )
    assert latency.status_code == 422, latency.text
    assert latency.json()["error"]["details"]["reasons"] == ["latency_limit_exceeded"]

    budget = api_client.post(
        f"/api/v1/projects/{project}/3d-generations/estimate",
        json={**body, "budget_usd": "1.00"},
        headers=actor.headers,
    )
    assert budget.status_code == 422, budget.text
    assert budget.json()["error"]["details"]["reasons"] == ["provider_cost_unknown"]


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
