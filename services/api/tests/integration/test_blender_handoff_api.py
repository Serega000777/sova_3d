from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import blender_handoff, exporters

import app.jobs.handlers  # noqa: F401
from app.jobs import runner
from app.models import Asset, Job, ProjectVersion, VersionAsset
from app.models.execution import JobStatus
from app.models.versioning import AssetRole, VersionState
from app.services import projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_exports_api import box_stl
from tests.integration.test_printing_api import seed_version


@pytest.fixture
def cleanup_keys(storage: S3Storage) -> Iterator[list[str]]:
    keys: list[str] = []
    yield keys
    for key in keys:
        storage.delete(key)


def _fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    objects: int = 1,
    animations: int = 0,
    animated_objects: list[str] | None = None,
    animation_paths: list[str] | None = None,
    observed_scene: list[exporters.SceneMeshInput] | None = None,
    observed_animation: list[exporters.SceneAnimationInput | None] | None = None,
) -> None:
    def export_mesh(
        _source: Path, _source_format: str, _target: str, output: Path, **_kwargs: Any
    ) -> exporters.ExportOutcome:
        output.write_bytes(b"glTF" + b"\0" * 64)
        return exporters.ExportOutcome(ok=True, output_path=str(output))

    def export_scene(
        inputs: list[exporters.SceneMeshInput],
        target: str,
        output: Path,
        **_kwargs: Any,
    ) -> exporters.ExportOutcome:
        assert target == "glb"
        for entry in inputs:
            if entry.texture_path is None:
                continue
            assert entry.appearance is not None
            texture = Path(entry.texture_path).read_bytes()
            assert hashlib.sha256(texture).hexdigest() == entry.appearance.texture_sha256
        if observed_scene is not None:
            observed_scene.extend(inputs)
        animation = _kwargs.get("animation")
        assert animation is None or isinstance(animation, exporters.SceneAnimationInput)
        if observed_animation is not None:
            observed_animation.append(animation)
        output.write_bytes(b"glTF" + b"\0" * 64)
        return exporters.ExportOutcome(ok=True, output_path=str(output))

    def package(source: Path, output: Path) -> blender_handoff.BlenderHandoffOutcome:
        output.write_bytes(b"BLENDER-v300" + b"\0" * 64)
        script = Path(blender_handoff.__file__).with_name("blender_handoff_script.py")
        return blender_handoff.BlenderHandoffOutcome(
            ok=True,
            report=blender_handoff.BlenderHandoffReport(
                schema_version=1,
                operation="editable_scene",
                blender_version="4.3.3",
                objects=objects,
                meshes=objects,
                materials=0,
                vertices=8 * objects,
                triangles=12 * objects,
                animations=animations,
                animated_objects=animated_objects or [],
                animation_paths=animation_paths or [],
                animation_keyframes=8 if animations else 0,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                min_bounds_m=[-0.01, -0.01, -0.01],
                max_bounds_m=[0.01, 0.01, 0.01],
                external_refs=[],
                scripts=[],
                drivers=[],
                packed=True,
                sandbox_network_interfaces=["lo"],
                sandbox_uid=65534,
                capability_effective="0000000000000000",
                capability_permitted="0000000000000000",
                capability_ambient="0000000000000000",
                no_new_privileges=True,
            ),
        )

    monkeypatch.setattr("app.jobs.blender_handoff.exporters.export_mesh", export_mesh)
    monkeypatch.setattr("app.jobs.blender_handoff.exporters.export_scene", export_scene)
    monkeypatch.setattr("app.jobs.blender_handoff.blender_handoff.package_editable_scene", package)


def test_finalized_model_creates_downloadable_blend_export(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    _fake_pipeline(monkeypatch)

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers={**actor.headers, "Idempotency-Key": "blend-1"},
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    result = job.result or {}
    assert result["format"] == "blend" and result["operation"] == "editable_scene"
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None and made.format == "blend" and made.mime == "application/x-blender"
    cleanup_keys.append(made.storage_key)
    assert storage.get(made.storage_key).startswith(b"BLENDER")
    assert db_session.get(VersionAsset, (version.id, made.id, AssetRole.export)) is not None

    download = api_client.get(f"/api/v1/assets/{made.id}/download", headers=actor.headers)
    assert download.status_code == 200
    assert download.json()["format"] == "blend"
    assert download.json()["byte_size"] == made.byte_size


def test_canonical_model_rejects_untrusted_animation(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    _fake_pipeline(
        monkeypatch,
        animations=1,
        animated_objects=["Part"],
        animation_paths=["rotation_quaternion"],
    )

    accepted = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers={**actor.headers, "Idempotency-Key": "untrusted-animation"},
    )
    assert accepted.status_code == 202, accepted.text
    failed = runner.run_once(db_session, storage, commit=db_session.flush)
    assert failed is not None and failed.status is JobStatus.failed
    assert (failed.error or {})["code"] == "scene_animation_mismatch"


def test_handoff_requires_editor_finalized_version_and_strict_body(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    draft_version = projects.create_version_internal(
        db_session,
        project_id=project.id,
        parent_version_id=version.id,
        label="Draft",
        provenance={"operation": "test_draft"},
        assets={AssetRole.model: source.id},
        finalize=False,
        created_by=actor.user.id,
    )
    assert draft_version.state is VersionState.draft
    draft = api_client.post(
        f"/api/v1/models/{draft_version.id}/blender-handoffs", json={}, headers=actor.headers
    )
    assert draft.status_code == 422
    extra = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs",
        json={"python": "print('unsafe')"},
        headers=actor.headers,
    )
    assert extra.status_code == 422

    stranger = make_actor(db_session)
    foreign = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=stranger.headers
    )
    assert foreign.status_code == 404

    unsupported_version = projects.create_version_internal(
        db_session,
        project_id=project.id,
        parent_version_id=version.id,
        label="Unsupported scene schema",
        provenance={"scene": {"schema_version": 999, "nodes": []}},
        assets={AssetRole.model: source.id},
        finalize=True,
        created_by=actor.user.id,
    )
    unsupported = api_client.post(
        f"/api/v1/models/{unsupported_version.id}/blender-handoffs",
        json={},
        headers=actor.headers,
    )
    assert unsupported.status_code == 422


def test_handoff_idempotency_reuses_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    headers = {**actor.headers, "Idempotency-Key": "same-blend"}
    first = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=headers
    )
    second = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=headers
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


def test_multi_object_scene_handoff_preserves_visible_objects_and_world_transforms(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    moved = [
        [1.0, 0.0, 0.0, 40.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "part",
                    "name": "Part",
                    "kind": "object",
                    "asset_id": str(source.id),
                },
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "part",
                    "transform": moved,
                },
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "instance_of": "part",
                    "visible": False,
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    scene_version_id = scene.json()["version_id"]
    assigned = api_client.post(
        f"/api/v1/models/{scene_version_id}/interior-material",
        json={
            "scene_node_id": "part",
            "catalog_material_id": "interior.wood.oak-natural.v1",
        },
        headers=actor.headers,
    )
    assert assigned.status_code == 201, assigned.text
    scene_version_id = assigned.json()["version_id"]
    observed: list[exporters.SceneMeshInput] = []
    _fake_pipeline(monkeypatch, objects=2, observed_scene=observed)

    accepted = api_client.post(
        f"/api/v1/models/{scene_version_id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    assert [entry.node_id for entry in observed] == ["part", "copy"]
    assert [entry.name for entry in observed] == ["Part", "Copy"]
    assert observed[1].world_transform == moved
    assert observed[0].path == observed[1].path  # the instance reuses one downloaded asset
    assert observed[0].appearance is not None
    assert observed[0].appearance.catalog_material_id == "interior.wood.oak-natural.v1"
    assert observed[0].texture_path is not None
    assert Path(observed[0].texture_path).name == (
        f"material-{observed[0].appearance.texture_sha256}.png"
    )
    result = job.result or {}
    assert result["report"]["scene"] == {
        "visible_objects": 2,
        "node_ids": ["part", "copy"],
        "asset_ids": [str(source.id), str(source.id)],
        "transforms_applied": True,
        "appearances_applied": True,
    }
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None
    cleanup_keys.append(made.storage_key)
    assert made.metadata_["scene"] == result["report"]["scene"]


def test_blender_handoff_rejects_scene_without_visible_geometry(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "asset_id": str(source.id),
                    "visible": False,
                }
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text

    rejected = api_client.post(
        f"/api/v1/models/{scene.json()['version_id']}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers=actor.headers,
    )
    assert rejected.status_code == 422
    assert "no visible geometry" in rejected.text


def test_trusted_mechanism_animation_is_preserved_and_wrong_target_fails_closed(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "part",
                    "name": "Part",
                    "kind": "object",
                    "asset_id": str(source.id),
                },
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "part",
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    scene_version = db_session.get(ProjectVersion, uuid.UUID(scene.json()["version_id"]))
    assert scene_version is not None
    animated_version = projects.create_version_internal(
        db_session,
        project_id=project.id,
        parent_version_id=scene_version.id,
        label="Trusted animated mechanism",
        provenance={
            **(scene_version.provenance or {}),
            "build_hinged_lid": {
                "kind": "hinged_lid",
                "joint": {
                    "type": "revolute",
                    "node_id": "copy",
                    "axis": "x",
                    "min_angle_deg": 0,
                    "max_angle_deg": 90,
                },
            },
        },
        assets={AssetRole.model: source.id},
        finalize=True,
        created_by=actor.user.id,
    )
    observed_animation: list[exporters.SceneAnimationInput | None] = []
    _fake_pipeline(
        monkeypatch,
        objects=2,
        animations=1,
        animated_objects=["Copy"],
        animation_paths=["rotation_quaternion"],
        observed_animation=observed_animation,
    )

    accepted = api_client.post(
        f"/api/v1/models/{animated_version.id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers={**actor.headers, "Idempotency-Key": "animated-blend-good"},
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.succeeded, job.error if job else None
    assert len(observed_animation) == 1 and observed_animation[0] is not None
    assert observed_animation[0].node_id == "copy"
    assert observed_animation[0].kind == "revolute"
    result = job.result or {}
    assert result["report"]["animated_objects"] == ["Copy"]
    assert result["report"]["animation_paths"] == ["rotation_quaternion"]
    assert result["report"]["scene"]["animation_kind"] == "revolute_joint"
    made = db_session.get(Asset, uuid.UUID(result["asset_id"]))
    assert made is not None
    cleanup_keys.append(made.storage_key)

    _fake_pipeline(
        monkeypatch,
        objects=2,
        animations=1,
        animated_objects=["Part"],
        animation_paths=["rotation_quaternion"],
    )
    wrong = api_client.post(
        f"/api/v1/models/{animated_version.id}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers={**actor.headers, "Idempotency-Key": "animated-blend-wrong"},
    )
    assert wrong.status_code == 202, wrong.text
    failed = runner.run_once(db_session, storage, commit=db_session.flush)
    assert failed is not None and failed.status is JobStatus.failed
    assert (failed.error or {})["code"] == "scene_animation_mismatch"


def test_worker_rejects_blender_scene_that_flattens_visible_objects(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    scene = api_client.post(
        f"/api/v1/models/{version.id}/scene",
        json={
            "nodes": [
                {
                    "id": "part",
                    "name": "Part",
                    "kind": "object",
                    "asset_id": str(source.id),
                },
                {
                    "id": "copy",
                    "name": "Copy",
                    "kind": "object",
                    "instance_of": "part",
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    _fake_pipeline(monkeypatch, objects=1)

    accepted = api_client.post(
        f"/api/v1/models/{scene.json()['version_id']}/blender-handoffs",
        json={"operation": "editable_scene"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    job = runner.run_once(db_session, storage, commit=db_session.flush)
    assert job is not None and job.status is JobStatus.failed
    assert (job.error or {})["code"] == "scene_structure_mismatch"
    assert (job.error or {})["details"] == {
        "expected_objects": 2,
        "reported_objects": 1,
        "reported_meshes": 1,
    }


def test_worker_revalidates_queued_lineage_before_blender(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project, version, source = seed_version(db_session, storage, actor, box_stl())
    cleanup_keys.append(source.storage_key)
    accepted = api_client.post(
        f"/api/v1/models/{version.id}/blender-handoffs", json={}, headers=actor.headers
    )
    job = db_session.get(Job, uuid.UUID(accepted.json()["job_id"]))
    assert job is not None
    job.project_id = None
    db_session.flush()
    launched = False

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal launched
        launched = True
        raise AssertionError("Blender must not run for invalid lineage")

    monkeypatch.setattr(
        "app.jobs.blender_handoff.blender_handoff.package_editable_scene", forbidden
    )
    runner.run_once(db_session, storage, commit=db_session.flush)
    db_session.refresh(job)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "lineage_invalid"
    assert launched is False
