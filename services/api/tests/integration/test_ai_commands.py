"""T-042/T-045..T-048: ai-command endpoint -> runner -> plan -> kernel -> version, clarification
loop, usage metering, workspace quota, history contract."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import geometry as kernel

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.jobs import runner
from app.models import AIRequest, Asset, Job, Operation, ProjectVersion, UsageEntry
from app.models.execution import AIRequestStatus, JobStatus
from app.models.versioning import AssetRole, VersionAsset
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


@pytest.fixture(autouse=True)
def kernel_or_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the real geometry-service when present; otherwise a fake that honours the plan."""
    if kernel.available():
        return

    def fake_execute(plan: dict[str, Any], out_dir: Path, **_: Any) -> kernel.KernelResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        bodies = []
        for op in plan["operations"]:
            if op["type"] == "create_box":
                mesh = trimesh.creation.box(
                    extents=(op["width_mm"], op["depth_mm"], op["height_mm"])
                )
                mesh.apply_translation(np.array(mesh.extents) / 2)
            elif op["type"] == "create_cylinder":
                mesh = trimesh.creation.cylinder(
                    radius=op["diameter_mm"] / 2, height=op["height_mm"]
                )
            else:
                continue
            stl = mesh.export(file_type="stl")
            stl_bytes = stl if isinstance(stl, bytes) else bytes(stl)
            (out_dir / f"{op['id']}.stl").write_bytes(stl_bytes)
            (out_dir / f"{op['id']}.brep").write_bytes(
                b"DBRep_DrawableShape\nfake " + op["id"].encode()
            )
            lo, hi = mesh.bounds.tolist()
            bodies.append(
                kernel.BodyResult(
                    name=op["id"],
                    bbox_mm=kernel.BBoxMM(
                        min=tuple(lo), max=tuple(hi), size=tuple(mesh.extents.tolist())
                    ),
                    volume_mm3=float(mesh.volume),
                    surface_area_mm2=float(mesh.area),
                    solids=1,
                    faces=6,
                    edges=12,
                    vertices=8,
                    valid=True,
                    brep=f"{op['id']}.brep",
                    stl=f"{op['id']}.stl",
                    brep_sha256=hashlib.sha256(op["id"].encode()).hexdigest(),
                    stl_sha256=hashlib.sha256(stl_bytes).hexdigest(),
                )
            )
        if not bodies:
            return kernel.KernelResult(
                ok=False, error=kernel.KernelFailure(code="empty_plan", message="no bodies")
            )
        return kernel.KernelResult(
            ok=True,
            kernel="fake/0",
            executed=[op["id"] for op in plan["operations"]],
            bodies=bodies,
            output_dir=str(out_dir),
        )

    monkeypatch.setattr(kernel, "execute_plan", fake_execute)


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def new_project(api_client: TestClient, actor: Actor) -> str:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "ai"},
        headers=actor.headers,
    ).json()["id"]
    return project_id


def command(
    api_client: TestClient, actor: Actor, project_id: str, prompt: str, **extra: Any
) -> Any:
    return api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": prompt, **extra},
        headers=actor.headers,
    )


def run_all(db: Session, storage: S3Storage) -> list[Job]:
    done: list[Job] = []
    while (job := runner.run_once(db, storage, commit=db.flush)) is not None:
        done.append(job)
    return done


# --- T-045 -----------------------------------------------------------------------------------


def test_ai_command_creates_version_with_operations_and_assets(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project_id = new_project(api_client, actor)
    response = command(api_client, actor, project_id, "Box 40x20x8 mm with 2 holes 5.5 mm")
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "planning" and accepted["job_status"] == "queued"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["status"] == "executed"
    assert [op["type"] for op in result["plan"]["operations"]] == [
        "create_box",
        "add_hole",
        "add_hole",
    ]

    version = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert version is not None and version.provenance["ai_request_id"] == accepted["ai_request_id"]
    ops = (
        db_session.query(Operation)
        .filter_by(project_version_id=version.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [(o.sequence_no, o.operation_type) for o in ops] == [
        (1, "create_box"),
        (2, "add_hole"),
        (3, "add_hole"),
    ]
    assert ops[0].params["width_mm"] == 40 and ops[0].ai_request_id == uuid.UUID(
        accepted["ai_request_id"]
    )

    roles = {
        link.role: link.asset_id
        for link in db_session.query(VersionAsset).filter_by(version_id=version.id)
    }
    assert set(roles) == {AssetRole.model, AssetRole.source}
    model = db_session.get(Asset, roles[AssetRole.model])
    source = db_session.get(Asset, roles[AssetRole.source])
    assert model is not None and model.format == "stl" and source is not None
    assert source.format == "brep"
    cleanup_keys.extend([model.storage_key, source.storage_key])
    assert (
        storage.get(model.storage_key)[:5] in (b"solid", b"\x00\x00\x00\x00\x00")
        or len(storage.get(model.storage_key)) > 84
    )
    assert storage.get(source.storage_key).startswith(b"DBRep_DrawableShape")

    request = db_session.get(AIRequest, uuid.UUID(accepted["ai_request_id"]))
    assert request is not None and request.status is AIRequestStatus.executed
    assert request.result_version_id == version.id
    assert request.output_plan is not None and request.output_plan["operations"]

    head = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert head["head_version_id"] == str(version.id)

    detail = api_client.get(
        f"/api/v1/ai-requests/{accepted['ai_request_id']}", headers=actor.headers
    ).json()
    assert detail["status"] == "executed" and detail["result_version_id"] == str(version.id)


def test_second_command_replays_current_operations(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project_id = new_project(api_client, actor)
    command(api_client, actor, project_id, "Box 30x30x10 mm")
    run_all(db_session, storage)
    first = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    v1 = first["head_version_id"]

    # The stub planner ignores context but the request must carry the replay log.
    request_id = command(api_client, actor, project_id, "Box 30x30x10 mm").json()["ai_request_id"]
    request = db_session.get(AIRequest, uuid.UUID(request_id))
    assert request is not None and request.project_version_id == uuid.UUID(v1)
    from app.services.ai_commands import plan_request_for

    plan_request = plan_request_for(db_session, request)
    assert [op["type"] for op in plan_request.current_operations] == ["create_box"]
    assert plan_request.current_operations[0]["id"] == "body"

    run_all(db_session, storage)
    second = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert second["head_version_id"] != v1
    assert second["head_version"]["parent_version_id"] == v1
    for asset in db_session.query(Asset).filter(Asset.workspace_id == actor.workspace.id):
        cleanup_keys.append(asset.storage_key)


# --- T-042 -----------------------------------------------------------------------------------


def test_missing_dimensions_pause_job_until_clarified(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project_id = new_project(api_client, actor)
    accepted = command(api_client, actor, project_id, "сделай коробку для ключей").json()
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.waiting_input
    assert job.result and job.result["status"] == "needs_clarification"

    request_id = accepted["ai_request_id"]
    detail = api_client.get(f"/api/v1/ai-requests/{request_id}", headers=actor.headers).json()
    assert detail["status"] == "needs_clarification"
    assert "Ш×Г×В" in detail["clarifications"][0]
    polled = api_client.get(f"/api/v1/jobs/{job.id}", headers=actor.headers).json()
    assert polled["status"] == "waiting_input"

    # Wrong number of answers is rejected; the right one resumes the same job.
    bad = api_client.post(
        f"/api/v1/ai-requests/{request_id}/clarify",
        json={"answers": ["a", "b"]},
        headers=actor.headers,
    )
    assert bad.status_code == 409
    resumed = api_client.post(
        f"/api/v1/ai-requests/{request_id}/clarify",
        json={"answers": ["50x30x20 мм"]},
        headers=actor.headers,
    )
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["job_id"] == str(job.id) and resumed.json()["job_status"] == "queued"

    (job2,) = run_all(db_session, storage)
    assert job2.id == job.id and job2.status is JobStatus.succeeded, job2.error
    detail = api_client.get(f"/api/v1/ai-requests/{request_id}", headers=actor.headers).json()
    assert detail["status"] == "executed" and detail["conversation"][0]["answer"] == "50x30x20 мм"
    assert detail["output_plan"]["operations"][0]["width_mm"] == 50
    again = api_client.post(
        f"/api/v1/ai-requests/{request_id}/clarify", json={"answers": ["x"]}, headers=actor.headers
    )
    assert again.status_code == 409
    for asset in db_session.query(Asset).filter(Asset.workspace_id == actor.workspace.id):
        cleanup_keys.append(asset.storage_key)


def test_unsupported_request_is_a_clarification_not_a_failure(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    project_id = new_project(api_client, actor)
    command(api_client, actor, project_id, "a dragon statue 10 cm")
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.waiting_input
    versions = api_client.get(
        f"/api/v1/projects/{project_id}/versions", headers=actor.headers
    ).json()
    assert versions == []


# --- T-046 / T-047 -----------------------------------------------------------------------------


def test_usage_is_metered_per_request(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project_id = new_project(api_client, actor)
    request_id = command(api_client, actor, project_id, "Box 10x10x10 mm").json()["ai_request_id"]
    run_all(db_session, storage)
    entries = db_session.query(UsageEntry).filter_by(ai_request_id=uuid.UUID(request_id)).all()
    assert len(entries) == 1
    assert entries[0].metadata_["provider"] == "stub" and entries[0].quantity > 0
    request = db_session.get(AIRequest, uuid.UUID(request_id))
    assert request is not None and request.tokens_in and request.tokens_out
    usage = api_client.get(
        "/api/v1/usage", params={"workspace_id": str(actor.workspace.id)}, headers=actor.headers
    ).json()
    assert usage["entries"] == 1 and Decimal(usage["budget_usd"]) == Decimal("20")
    for asset in db_session.query(Asset).filter(Asset.workspace_id == actor.workspace.id):
        cleanup_keys.append(asset.storage_key)


def test_workspace_quota_blocks_new_commands(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    from app.models.usage import UsageKind
    from app.services import usage as usage_service

    actor.workspace.ai_monthly_budget_usd = Decimal("1.00")
    usage_service.record(
        db_session,
        workspace_id=actor.workspace.id,
        kind=UsageKind.ai_tokens,
        quantity=1000,
        unit="token",
        cost_usd=Decimal("1.00"),
    )
    project_id = new_project(api_client, actor)
    response = command(api_client, actor, project_id, "Box 10x10x10 mm")
    assert response.status_code == 402
    body = response.json()["error"]
    assert body["code"] == "ai_quota_exceeded" and body["details"]["budget_usd"] == "1.00"
    assert db_session.query(AIRequest).count() == 0


# --- T-048 / scoping --------------------------------------------------------------------------


def test_history_contract_and_scoping(
    api_client: TestClient, db_session: Session, storage: S3Storage, cleanup_keys: list[str]
) -> None:
    owner = make_actor(db_session)
    stranger = make_actor(db_session)
    project_id = new_project(api_client, owner)
    first = command(api_client, owner, project_id, "Box 10x10x10 mm").json()
    second = command(api_client, owner, project_id, "make me a box").json()
    run_all(db_session, storage)

    history = api_client.get(
        f"/api/v1/projects/{project_id}/ai-requests", headers=owner.headers
    ).json()
    assert [h["id"] for h in history] == [second["ai_request_id"], first["ai_request_id"]]
    by_id = {h["id"]: h for h in history}
    assert by_id[first["ai_request_id"]]["status"] == "executed"
    assert by_id[first["ai_request_id"]]["result_version_id"]
    assert by_id[second["ai_request_id"]]["status"] == "needs_clarification"
    assert by_id[second["ai_request_id"]]["clarifications"]

    assert command(api_client, stranger, project_id, "Box 1x1x1 mm").status_code == 404
    assert (
        api_client.get(
            f"/api/v1/ai-requests/{first['ai_request_id']}", headers=stranger.headers
        ).status_code
        == 404
    )
    assert (
        api_client.get(
            f"/api/v1/projects/{project_id}/ai-requests", headers=stranger.headers
        ).status_code
        == 404
    )
    for asset in db_session.query(Asset).filter(Asset.workspace_id == owner.workspace.id):
        cleanup_keys.append(asset.storage_key)


def test_idempotent_command(api_client: TestClient, actor: Actor) -> None:
    project_id = new_project(api_client, actor)
    headers = {**actor.headers, "Idempotency-Key": "cmd-1"}
    a = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Box 1x1x1 mm"},
        headers=headers,
    ).json()
    b = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Box 1x1x1 mm"},
        headers=headers,
    ).json()
    assert a == b
