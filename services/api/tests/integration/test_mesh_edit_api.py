"""F-086 (T-235 / T-236): direct mesh edits and surface details are new versions."""

from __future__ import annotations

import io
from typing import Any

import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Asset, ProjectVersion
from app.models.execution import JobStatus, Operation
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401
from tests.integration.test_painting_api import corner_box_stl, imported_version

BOX_VOLUME = 30 * 20 * 10
# the top face of the 30 x 20 x 10 box that sits at the origin, in model mm
TOP_CORNERS = [[0, 0, 10], [30, 0, 10], [30, 20, 10], [0, 20, 10]]
CIRCLE = {"shape": "circle", "diameter_mm": 6.0}
IDENTITY = [
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
]


def translated(x: float) -> list[list[float]]:
    value = [row[:] for row in IDENTITY]
    value[0][3] = x
    return value


def rotated_y_with_translation(x: float) -> list[list[float]]:
    return [
        [0, 0, 1, x],
        [0, 1, 0, 0],
        [-1, 0, 0, 0],
        [0, 0, 0, 1],
    ]


def transform_point(matrix: list[list[float]], point: list[float]) -> list[float]:
    return [
        sum(matrix[row][axis] * point[axis] for axis in range(3)) + matrix[row][3]
        for row in range(3)
    ]


def detail(profile: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "op": "detail",
        "at_mm": [15, 10, 10],
        "normal_hint": [0, 0, 1],
        "profile": profile or CIRCLE,
        "depth_mm": 2.0,
        **extra,
    }


def edit(
    api_client: TestClient, actor: Actor, version_id: str, *operations: Any, **body: Any
) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/mesh-edit",
        json={"operations": list(operations), **body},
        headers=actor.headers,
    )


def stored_mesh(db_session: Session, storage: S3Storage, version_id: str) -> trimesh.Trimesh:
    version = db_session.get(ProjectVersion, version_id)
    assert version is not None
    model = {link.role: link.asset_id for link in version.assets}[AssetRole.model]
    asset = db_session.get(Asset, model)
    assert asset is not None
    return trimesh.load(io.BytesIO(storage.get(asset.storage_key)), file_type="stl", force="mesh")


def stored_asset_mesh(db_session: Session, storage: S3Storage, asset_id: str) -> trimesh.Trimesh:
    asset = db_session.get(Asset, asset_id)
    assert asset is not None
    return trimesh.load(io.BytesIO(storage.get(asset.storage_key)), file_type="stl", force="mesh")


def test_a_surface_detail_becomes_a_new_watertight_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = edit(
        api_client, actor, version_id, detail(mode="raised"), label="Boss", expected_faces=12
    )
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["report"]["after"]["watertight"] is True

    edited = db_session.get(ProjectVersion, result["version_id"])
    assert edited is not None and edited.label == "Boss"
    assert str(edited.parent_version_id) == version_id
    assert edited.provenance["mesh_edit"]["operations"][0]["op"] == "detail"
    mesh = stored_mesh(db_session, storage, result["version_id"])
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(BOX_VOLUME + 3.14159 * 3.0**2 * 2.0, rel=0.01)

    # the original is untouched: an edit is a child version, never an overwrite
    original = stored_mesh(db_session, storage, version_id)
    assert original.volume == pytest.approx(BOX_VOLUME)


def test_mesh_edits_append_to_a_replayable_modifier_stack(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    base_id = imported_version(api_client, actor, db_session, storage, project)
    first = edit(api_client, actor, base_id, detail(mode="raised"))
    assert first.status_code == 202, first.text
    (first_job,) = run_all(db_session, storage)
    assert first_job.status is JobStatus.succeeded, first_job.error
    first_id = str((first_job.result or {})["version_id"])

    second_detail = detail(
        {"shape": "circle", "diameter_mm": 4.0},
        at_mm=[5, 5, 10],
        mode="raised",
    )
    second = edit(api_client, actor, first_id, second_detail)
    assert second.status_code == 202, second.text
    (second_job,) = run_all(db_session, storage)
    assert second_job.status is JobStatus.succeeded, second_job.error
    second_id = str((second_job.result or {})["version_id"])

    stack = api_client.get(f"/api/v1/models/{second_id}/mesh-modifier-stack", headers=actor.headers)
    assert stack.status_code == 200, stack.text
    body = stack.json()
    assert body["base_version_id"] == base_id
    assert [item["id"] for item in body["modifiers"]] == ["mesh_1", "mesh_2"]
    assert [item["type"] for item in body["modifiers"]] == ["detail", "detail"]
    assert all(item["enabled"] for item in body["modifiers"])

    reordered = api_client.post(
        f"/api/v1/models/{second_id}/mesh-modifier-stack",
        json={
            "modifiers": [
                {"id": "mesh_2", "enabled": True},
                {"id": "mesh_1", "enabled": True},
            ]
        },
        headers=actor.headers,
    )
    assert reordered.status_code == 202, reordered.text
    (reordered_job,) = run_all(db_session, storage)
    assert reordered_job.status is JobStatus.succeeded, reordered_job.error
    reordered_id = str((reordered_job.result or {})["version_id"])
    reordered_stack = api_client.get(
        f"/api/v1/models/{reordered_id}/mesh-modifier-stack", headers=actor.headers
    ).json()
    assert [item["id"] for item in reordered_stack["modifiers"]] == ["mesh_2", "mesh_1"]

    rebuilt = api_client.post(
        f"/api/v1/models/{reordered_id}/mesh-modifier-stack",
        json={
            "modifiers": [
                {"id": "mesh_1", "enabled": True},
                {"id": "mesh_2", "enabled": False},
            ],
            "label": "Only first boss",
        },
        headers=actor.headers,
    )
    assert rebuilt.status_code == 202, rebuilt.text
    (rebuilt_job,) = run_all(db_session, storage)
    assert rebuilt_job.status is JobStatus.succeeded, rebuilt_job.error
    rebuilt_id = str((rebuilt_job.result or {})["version_id"])
    rebuilt_mesh = stored_mesh(db_session, storage, rebuilt_id)
    assert rebuilt_mesh.volume == pytest.approx(BOX_VOLUME + 3.14159 * 3.0**2 * 2.0, rel=0.01)
    rebuilt_stack = api_client.get(
        f"/api/v1/models/{rebuilt_id}/mesh-modifier-stack", headers=actor.headers
    ).json()
    assert [item["enabled"] for item in rebuilt_stack["modifiers"]] == [True, False]


def test_mesh_modifier_stack_rejects_incomplete_or_empty_active_sets(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    base_id = imported_version(api_client, actor, db_session, storage, project)
    assert edit(api_client, actor, base_id, detail(mode="raised")).status_code == 202
    (job,) = run_all(db_session, storage)
    version_id = str((job.result or {})["version_id"])
    url = f"/api/v1/models/{version_id}/mesh-modifier-stack"

    missing = api_client.post(url, json={"modifiers": []}, headers=actor.headers)
    assert missing.status_code == 422
    unknown = api_client.post(
        url,
        json={"modifiers": [{"id": "mesh_unknown", "enabled": True}]},
        headers=actor.headers,
    )
    assert unknown.status_code == 422
    disabled = api_client.post(
        url,
        json={"modifiers": [{"id": "mesh_1", "enabled": False}]},
        headers=actor.headers,
    )
    assert disabled.status_code == 422
    assert run_all(db_session, storage) == []


def test_a_preview_reports_the_footprint_and_creates_nothing(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    count_before = db_session.query(ProjectVersion).count()
    response = edit(api_client, actor, version_id, detail(), preview=True)
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["preview"] is True
    preview = result["report"]["preview"]
    assert len(preview["footprints_mm"]) == 1
    assert preview["estimated_added_triangles"] > 0
    assert db_session.query(ProjectVersion).count() == count_before


def test_moving_and_extruding_components_by_position(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    move = {
        "op": "move",
        "selection": {"kind": "vertex", "points_mm": TOP_CORNERS},
        "delta_mm": [0, 0, 4],
    }
    edit(api_client, actor, version_id, move)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    mesh = stored_mesh(db_session, storage, str((job.result or {})["version_id"]))
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(30 * 20 * 14)
    assert mesh.bounds[1][2] == pytest.approx(14.0)


def test_a_refused_detail_fails_the_job_with_the_reason(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    edit(api_client, actor, version_id, detail({"shape": "circle", "diameter_mm": 0.05}))
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "below_tolerance"
    # no half-made version is left behind
    assert db_session.query(ProjectVersion).filter_by(parent_version_id=version_id).count() == 0


def test_a_stale_selection_is_reported_with_its_operation(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    edit(api_client, actor, version_id, detail(), expected_faces=999)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "stale_selection"


def test_an_invalid_request_is_a_422_before_anything_is_queued(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    bad = edit(api_client, actor, version_id, {"op": "teleport"})
    assert bad.status_code == 422, bad.text
    assert run_all(db_session, storage) == []
    arity = edit(
        api_client,
        actor,
        version_id,
        {
            "op": "extrude",
            "selection": {"kind": "face", "points_mm": [[0, 0, 0]]},
            "distance_mm": 1,
        },
    )
    assert arity.status_code == 422, arity.text


def test_a_parametric_version_needs_explicit_consent_to_become_a_mesh(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    db_session.add(
        Operation(
            project_version_id=version_id,
            sequence_no=1,
            operation_type="create_box",
            schema_version=1,
            params={},
            entity_refs={},
        )
    )
    db_session.flush()

    refused = edit(api_client, actor, version_id, detail())
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"]["parametric"] is True

    # looking is always allowed: a preview changes nothing
    assert edit(api_client, actor, version_id, detail(), preview=True).status_code == 202
    (previewed,) = run_all(db_session, storage)
    assert previewed.status is JobStatus.succeeded, previewed.error

    allowed = edit(api_client, actor, version_id, detail(), convert_to_mesh=True)
    assert allowed.status_code == 202, allowed.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    made = db_session.get(ProjectVersion, (job.result or {})["version_id"])
    assert made is not None
    assert made.provenance["mesh_edit"]["converted_from_parametric"] is True


def test_an_unknown_version_is_not_found(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    missing = "00000000-0000-0000-0000-000000000001"
    assert edit(api_client, actor, missing, detail()).status_code == 404


def test_the_box_fixture_is_what_the_selections_assume() -> None:
    mesh = trimesh.load(io.BytesIO(corner_box_stl()), file_type="stl", force="mesh")
    assert mesh.bounds.tolist() == [[0, 0, 0], [30, 20, 10]]
    assert len(mesh.faces) == 12


def test_scene_node_edit_replaces_only_that_geometry_and_keeps_independent_stacks(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    asset_id = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers).json()[
        "nodes"
    ][0]["asset_id"]
    made = api_client.post(
        f"/api/v1/models/{source_id}/scene",
        json={
            "nodes": [
                {"id": "part", "name": "Part", "kind": "object", "asset_id": asset_id},
                {
                    "id": "unique_copy",
                    "name": "Unique copy",
                    "kind": "object",
                    "asset_id": asset_id,
                    "transform": rotated_y_with_translation(100),
                },
                {
                    "id": "linked_copy",
                    "name": "Linked copy",
                    "kind": "object",
                    "instance_of": "part",
                    "transform": translated(200),
                },
            ]
        },
        headers=actor.headers,
    )
    assert made.status_code == 201, made.text
    scene_id = made.json()["version_id"]
    world_transform = rotated_y_with_translation(100)
    preview = edit(
        api_client,
        actor,
        scene_id,
        detail(
            at_mm=transform_point(world_transform, [15, 10, 10]),
            normal_hint=[1, 0, 0],
        ),
        scene_node_id="unique_copy",
        preview=True,
        expected_faces=12,
    )
    assert preview.status_code == 202, preview.text
    (preview_job,) = run_all(db_session, storage)
    assert preview_job.status is JobStatus.succeeded, preview_job.error
    outlines = (preview_job.result or {})["report"]["preview"]["footprints_mm"]
    assert outlines and all(point[0] == pytest.approx(110) for point in outlines[0])

    world_top = [transform_point(world_transform, point) for point in TOP_CORNERS]
    moved = edit(
        api_client,
        actor,
        scene_id,
        {
            "op": "move",
            "selection": {"kind": "vertex", "points_mm": world_top},
            "delta_mm": [4, 0, 0],
        },
        scene_node_id="unique_copy",
        expected_faces=12,
    )
    assert moved.status_code == 202, moved.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    edited_id = str((job.result or {})["version_id"])

    edited_scene = api_client.get(f"/api/v1/models/{edited_id}/scene", headers=actor.headers).json()
    by_id = {node["id"]: node for node in edited_scene["nodes"]}
    assert by_id["part"]["resolved_asset_id"] == asset_id
    assert by_id["linked_copy"]["resolved_asset_id"] == asset_id
    assert by_id["unique_copy"]["resolved_asset_id"] != asset_id
    assert by_id["unique_copy"]["world_transform"][0][3] == 100

    edited_mesh = stored_asset_mesh(db_session, storage, by_id["unique_copy"]["resolved_asset_id"])
    assert edited_mesh.bounds[1][2] == pytest.approx(14.0)
    assert (
        api_client.get(
            f"/api/v1/models/{edited_id}/mesh-modifier-stack",
            headers=actor.headers,
        ).status_code
        == 422
    )
    unique_stack = api_client.get(
        f"/api/v1/models/{edited_id}/mesh-modifier-stack?scene_node_id=unique_copy",
        headers=actor.headers,
    )
    assert unique_stack.status_code == 200, unique_stack.text
    assert unique_stack.json()["scene_node_id"] == "unique_copy"
    assert [item["id"] for item in unique_stack.json()["modifiers"]] == ["mesh_1"]

    part_moved = edit(
        api_client,
        actor,
        edited_id,
        {
            "op": "move",
            "selection": {"kind": "vertex", "points_mm": TOP_CORNERS},
            "delta_mm": [0, 0, 2],
        },
        scene_node_id="part",
        expected_faces=12,
    )
    assert part_moved.status_code == 202, part_moved.text
    (part_job,) = run_all(db_session, storage)
    assert part_job.status is JobStatus.succeeded, part_job.error
    twice_id = str((part_job.result or {})["version_id"])
    for node_id, key in (("unique_copy", "mesh_1"), ("part", "mesh_2")):
        stack = api_client.get(
            f"/api/v1/models/{twice_id}/mesh-modifier-stack?scene_node_id={node_id}",
            headers=actor.headers,
        )
        assert stack.status_code == 200, stack.text
        assert [item["id"] for item in stack.json()["modifiers"]] == [key]

    rebuilt = api_client.post(
        f"/api/v1/models/{twice_id}/mesh-modifier-stack",
        json={
            "scene_node_id": "unique_copy",
            "modifiers": [{"id": "mesh_1", "enabled": True}],
        },
        headers=actor.headers,
    )
    assert rebuilt.status_code == 202, rebuilt.text
    (rebuilt_job,) = run_all(db_session, storage)
    assert rebuilt_job.status is JobStatus.succeeded, rebuilt_job.error
    twice_id = str((rebuilt_job.result or {})["version_id"])
    assert (
        api_client.get(
            f"/api/v1/models/{twice_id}/mesh-modifier-stack?scene_node_id=part",
            headers=actor.headers,
        ).status_code
        == 200
    )

    twice_scene = api_client.get(f"/api/v1/models/{twice_id}/scene", headers=actor.headers).json()
    twice_scene["nodes"][0]["name"] = "Renamed part"
    rearranged = api_client.post(
        f"/api/v1/models/{twice_id}/scene",
        json={"nodes": twice_scene["nodes"]},
        headers=actor.headers,
    )
    assert rearranged.status_code == 201, rearranged.text
    rearranged_id = rearranged.json()["version_id"]
    for node_id in ("unique_copy", "part"):
        assert (
            api_client.get(
                f"/api/v1/models/{rearranged_id}/mesh-modifier-stack?scene_node_id={node_id}",
                headers=actor.headers,
            ).status_code
            == 200
        )


def test_scene_mesh_edit_requires_a_unique_rigid_direct_object(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    asset_id = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers).json()[
        "nodes"
    ][0]["asset_id"]
    scaled = [row[:] for row in IDENTITY]
    scaled[0][0] = 2
    made = api_client.post(
        f"/api/v1/models/{source_id}/scene",
        json={
            "nodes": [
                {"id": "group", "name": "Group", "kind": "group"},
                {"id": "part", "name": "Part", "kind": "object", "asset_id": asset_id},
                {
                    "id": "instance",
                    "name": "Instance",
                    "kind": "object",
                    "instance_of": "part",
                },
                {
                    "id": "scaled",
                    "name": "Scaled",
                    "kind": "object",
                    "asset_id": asset_id,
                    "transform": scaled,
                },
            ]
        },
        headers=actor.headers,
    )
    assert made.status_code == 201, made.text
    scene_id = made.json()["version_id"]
    for target, message in (
        ("group", "only a geometry object"),
        ("instance", "made unique"),
        ("scaled", "must be rigid"),
        ("missing", "does not exist"),
    ):
        refused = edit(
            api_client,
            actor,
            scene_id,
            detail(),
            scene_node_id=target,
        )
        assert refused.status_code == 422, refused.text
        assert message in refused.text
    assert edit(api_client, actor, scene_id, detail()).status_code == 422
    assert run_all(db_session, storage) == []
