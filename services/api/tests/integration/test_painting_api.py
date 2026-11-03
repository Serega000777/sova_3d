"""E14 (F-034): colour a model. The shape never changes; the colour is a new version."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from lxml import etree
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Asset, ProjectVersion
from app.models.core import WorkspaceRole
from app.models.execution import JobStatus
from app.models.versioning import AssetRole
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all, upload  # noqa: F401

TOP_FACE = {
    "kind": "lasso",
    "axis": "z",
    "offset_mm": 10,
    "depth_mm": 2,
    "points_mm": [[5, 5], [25, 5], [25, 15], [5, 15]],
}


def corner_box_stl() -> bytes:
    """A 30 × 20 × 10 box sitting at the origin, like everything the kernel makes."""
    import trimesh

    mesh = trimesh.creation.box(extents=(30, 20, 10))
    mesh.apply_translation([15, 10, 5])
    exported = mesh.export(file_type="stl")
    return exported if isinstance(exported, bytes) else str(exported).encode()


def imported_version(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> str:
    """A 30 × 20 × 10 box, uploaded the way a user would."""
    asset_id = upload(api_client, actor, corner_box_stl(), "box.stl", "model/stl")
    api_client.post(
        f"/api/v1/projects/{project_id}/imports",
        json={"asset_id": asset_id},
        headers=actor.headers,
    )
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def paint(api_client: TestClient, actor: Actor, version_id: str, **body: Any) -> Any:
    return api_client.post(f"/api/v1/models/{version_id}/paint", json=body, headers=actor.headers)


def reorder(
    api_client: TestClient,
    actor: Actor,
    version_id: str,
    layer_order: list[str],
    *,
    scene_node_id: str | None = None,
) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/paint/reorder-layers",
        json={"layer_order": layer_order, "scene_node_id": scene_node_id},
        headers=actor.headers,
    )


def test_painting_keeps_the_shape_and_adds_a_coloured_preview(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    before = db_session.get(ProjectVersion, version_id)
    assert before is not None
    model_asset = {link.role: link.asset_id for link in before.assets}[AssetRole.model]

    response = paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "opacity": 0.85, "region": TOP_FACE}],
        label="Red top",
        layer_name="  Front accent  ",
    )
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["paint"]["painted_faces"] > 0
    assert "#ff5533" in result["paint"]["colours"]

    painted = db_session.get(ProjectVersion, result["version_id"])
    assert painted is not None
    roles = {link.role: link.asset_id for link in painted.assets}
    # The printable model is the same asset — colour is not a change of shape.
    assert roles[AssetRole.model] == model_asset
    preview = db_session.get(Asset, roles[AssetRole.preview])
    assert preview is not None and preview.format == "glb"
    assert painted.label == "Red top"
    assert painted.provenance["paint"]["strokes"][0]["colour"] == "#ff5533"
    assert painted.provenance["paint"]["strokes"][0]["opacity"] == 0.85
    assert painted.provenance["paint"]["layers"] == [
        {"name": "Front accent", "stroke_start": 0, "stroke_count": 1}
    ]
    assert result["paint"]["layers"] == painted.provenance["paint"]["layers"]


def test_scene_paint_targets_one_translated_scaled_object_and_preserves_siblings(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    original = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers).json()[
        "nodes"
    ][0]["resolved_asset_id"]
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    scaled = [[0, 0.5, 0, 10], [2, 0, 0, 0], [0, 0, 1.5, 0], [0, 0, 0, 1]]
    assembled = api_client.post(
        f"/api/v1/models/{source_id}/scene",
        json={
            "nodes": [
                {"id": "root", "name": "Assembly", "kind": "group"},
                {
                    "id": "part",
                    "name": "Painted part",
                    "kind": "object",
                    "parent_id": "root",
                    "transform": scaled,
                    "asset_id": original,
                },
                {
                    "id": "sibling",
                    "name": "Untouched sibling",
                    "kind": "object",
                    "parent_id": "root",
                    "transform": identity,
                    "asset_id": original,
                },
                {
                    "id": "linked",
                    "name": "Linked instance",
                    "kind": "object",
                    "parent_id": "root",
                    "transform": identity,
                    "instance_of": "part",
                },
            ]
        },
        headers=actor.headers,
    )
    assert assembled.status_code == 201, assembled.text
    assembled_id = assembled.json()["version_id"]
    material_id = "interior.wood.oak-natural.v1"
    assigned = api_client.post(
        f"/api/v1/models/{assembled_id}/interior-material",
        json={"scene_node_id": "part", "catalog_material_id": material_id},
        headers=actor.headers,
    )
    assert assigned.status_code == 201, assigned.text
    assembled_id = assigned.json()["version_id"]
    assert (
        next(node for node in assigned.json()["nodes"] if node["id"] == "part")["appearance"][
            "catalog_material_id"
        ]
        == material_id
    )
    world_top = {
        **TOP_FACE,
        "offset_mm": TOP_FACE["offset_mm"] * 1.5,
        "depth_mm": TOP_FACE["depth_mm"] * 1.5,
        "points_mm": [[10 + y * 0.5, x * 2] for x, y in TOP_FACE["points_mm"]],
    }
    local_box = {"kind": "box", "min_mm": [0, 0, 8], "max_mm": [30, 20, 11]}
    world_box = {"kind": "box", "min_mm": [10, 0, 12], "max_mm": [20, 60, 16.5]}
    assert (
        paint(
            api_client,
            actor,
            assembled_id,
            strokes=[{"colour": "#ff5533", "region": world_top}],
            layer_name="Part accent",
        ).status_code
        == 422
    )
    response = paint(
        api_client,
        actor,
        assembled_id,
        scene_node_id="part",
        strokes=[{"colour": "#ff5533", "opacity": 0.85, "region": world_top}],
        layer_name="Part accent",
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["scene_node_id"] == "part"

    painted_id = result["version_id"]
    scene = api_client.get(f"/api/v1/models/{painted_id}/scene", headers=actor.headers).json()[
        "nodes"
    ]
    by_id = {node["id"]: node for node in scene}
    assert by_id["part"]["resolved_asset_id"] == result["painted_asset_id"]
    assert by_id["part"]["appearance"] is None
    assert by_id["part"]["world_transform"] == scaled
    assert by_id["part"]["parent_id"] == "root"
    assert by_id["sibling"]["resolved_asset_id"] == original
    assert by_id["sibling"]["world_transform"] == identity
    assert by_id["linked"]["resolved_asset_id"] == result["painted_asset_id"]

    made = db_session.get(ProjectVersion, painted_id)
    assert made is not None
    record = made.provenance["scene_paint"]["part"]
    assert record["source_asset_id"] == original
    assert record["painted_asset_id"] == result["painted_asset_id"]
    assert record["strokes"] == [{"colour": "#ff5533", "opacity": 0.85, "region": TOP_FACE}]
    assert record["layers"] == [{"name": "Part accent", "stroke_start": 0, "stroke_count": 1}]
    assert made.provenance["scene_paint_edit"]["cleared_material_id"] == material_id

    # A second node-scoped layer and its reorder replay only this target's trusted local history.
    second = paint(
        api_client,
        actor,
        painted_id,
        scene_node_id="part",
        strokes=[{"colour": "#1188ff", "region": world_box}],
        layer_name="Edge accent",
    )
    assert second.status_code == 202, second.text
    (second_job,) = run_all(db_session, storage)
    assert second_job.status is JobStatus.succeeded, second_job.error
    second_id = str((second_job.result or {})["version_id"])
    reordered = reorder(
        api_client,
        actor,
        second_id,
        ["Edge accent", "Part accent"],
        scene_node_id="part",
    )
    assert reordered.status_code == 202, reordered.text
    (reorder_job,) = run_all(db_session, storage)
    assert reorder_job.status is JobStatus.succeeded, reorder_job.error
    painted_id = str((reorder_job.result or {})["version_id"])
    made = db_session.get(ProjectVersion, painted_id)
    assert made is not None
    record = made.provenance["scene_paint"]["part"]
    assert [layer["name"] for layer in record["layers"]] == ["Edge accent", "Part accent"]
    assert record["strokes"][0]["region"] == local_box
    scene = api_client.get(f"/api/v1/models/{painted_id}/scene", headers=actor.headers).json()[
        "nodes"
    ]
    by_id = {node["id"]: node for node in scene}
    assert by_id["sibling"]["resolved_asset_id"] == original
    assert by_id["linked"]["resolved_asset_id"] == by_id["part"]["resolved_asset_id"]
    assert by_id["part"]["appearance"] is None

    # A metadata-only scene edit carries paint by the same stable direct node id and asset.
    renamed_nodes = [
        {**node, "name": "Renamed painted part"} if node["id"] == "part" else node for node in scene
    ]
    renamed = api_client.post(
        f"/api/v1/models/{painted_id}/scene",
        json={"nodes": renamed_nodes},
        headers=actor.headers,
    )
    assert renamed.status_code == 201, renamed.text
    renamed_row = db_session.get(ProjectVersion, renamed.json()["version_id"])
    assert renamed_row is not None
    assert renamed_row.provenance["scene_paint"]["part"] == record

    # Replacing that node's geometry drops its paint instead of transferring by name or sibling.
    replacement_nodes = [
        {**node, "asset_id": original, "instance_of": None} if node["id"] == "part" else node
        for node in renamed.json()["nodes"]
    ]
    replaced = api_client.post(
        f"/api/v1/models/{renamed.json()['version_id']}/scene",
        json={"nodes": replacement_nodes},
        headers=actor.headers,
    )
    assert replaced.status_code == 201, replaced.text
    replaced_row = db_session.get(ProjectVersion, replaced.json()["version_id"])
    assert replaced_row is not None
    assert replaced_row.provenance["scene_paint"] == {}
    assert replaced_row.provenance["scene_edit"]["dropped_paint_node_ids"] == ["part"]


def test_scene_paint_supports_arbitrary_affine_direct_nodes_and_rejects_other_targets(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id = imported_version(api_client, actor, db_session, storage, project)
    asset_id = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers).json()[
        "nodes"
    ][0]["resolved_asset_id"]
    diagonal = 2**-0.5
    rotated = [
        [diagonal, -diagonal, 0, 0],
        [diagonal, diagonal, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    sheared = [[1, 0.25, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    forged_internal = paint(
        api_client,
        actor,
        source_id,
        strokes=[
            {
                "colour": "#ff5533",
                "region": {
                    "kind": "affine",
                    "region": TOP_FACE,
                    "object_to_world": rotated,
                },
            }
        ],
    )
    assert forged_internal.status_code == 422
    scene = api_client.post(
        f"/api/v1/models/{source_id}/scene",
        json={
            "nodes": [
                {"id": "root", "name": "Root", "kind": "group"},
                {
                    "id": "part",
                    "name": "Rotated",
                    "kind": "object",
                    "parent_id": "root",
                    "transform": rotated,
                    "asset_id": asset_id,
                },
                {
                    "id": "copy",
                    "name": "Instance",
                    "kind": "object",
                    "instance_of": "part",
                },
                {
                    "id": "hidden",
                    "name": "Hidden",
                    "kind": "object",
                    "visible": False,
                    "asset_id": asset_id,
                },
                {
                    "id": "sheared",
                    "name": "Sheared",
                    "kind": "object",
                    "transform": sheared,
                    "asset_id": asset_id,
                },
            ]
        },
        headers=actor.headers,
    )
    assert scene.status_code == 201, scene.text
    version_id = scene.json()["version_id"]

    def status(
        target: str, request_actor: Actor = actor, region: dict[str, Any] | None = None
    ) -> int:
        return paint(
            api_client,
            request_actor,
            version_id,
            scene_node_id=target,
            strokes=[{"colour": "#ff5533", "region": region or TOP_FACE}],
            layer_name="Affine accent",
        ).status_code

    assert status("root") == 422
    assert status("copy") == 422
    assert status("hidden") == 422
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    assert status("part", viewer) == 403
    stranger = make_actor(db_session)
    assert status("part", stranger) == 404

    rotated_top = {
        **TOP_FACE,
        "points_mm": [[diagonal * (x - y), diagonal * (x + y)] for x, y in TOP_FACE["points_mm"]],
    }
    assert status("part", region=rotated_top) == 202
    (rotated_job,) = run_all(db_session, storage)
    assert rotated_job.status is JobStatus.succeeded, rotated_job.error
    rotated_version = db_session.get(ProjectVersion, (rotated_job.result or {})["version_id"])
    assert rotated_version is not None
    rotated_record = rotated_version.provenance["scene_paint"]["part"]
    assert rotated_record["strokes"][0]["region"] == {
        "kind": "affine",
        "region": rotated_top,
        "object_to_world": rotated,
    }
    rotated_nodes = api_client.get(
        f"/api/v1/models/{rotated_version.id}/scene", headers=actor.headers
    ).json()["nodes"]
    moved_rotated = [row[:] for row in rotated]
    moved_rotated[0][3] = 100
    moved_rotated[1][3] = 50
    moved = api_client.post(
        f"/api/v1/models/{rotated_version.id}/scene",
        json={
            "nodes": [
                {**node, "transform": moved_rotated} if node["id"] == "part" else node
                for node in rotated_nodes
            ]
        },
        headers=actor.headers,
    )
    assert moved.status_code == 201, moved.text
    replay = reorder(
        api_client,
        actor,
        moved.json()["version_id"],
        ["Affine accent"],
        scene_node_id="part",
    )
    assert replay.status_code == 202, replay.text
    (replay_job,) = run_all(db_session, storage)
    assert replay_job.status is JobStatus.succeeded, replay_job.error
    replay_nodes = api_client.get(
        f"/api/v1/models/{(replay_job.result or {})['version_id']}/scene", headers=actor.headers
    ).json()["nodes"]
    assert (
        next(node for node in replay_nodes if node["id"] == "part")["world_transform"]
        == moved_rotated
    )

    sheared_top = {
        **TOP_FACE,
        "points_mm": [[x + 0.25 * y, y] for x, y in TOP_FACE["points_mm"]],
    }
    assert status("sheared", region=sheared_top) == 202
    (sheared_job,) = run_all(db_session, storage)
    assert sheared_job.status is JobStatus.succeeded, sheared_job.error
    sheared_version = db_session.get(ProjectVersion, (sheared_job.result or {})["version_id"])
    assert sheared_version is not None
    sheared_record = sheared_version.provenance["scene_paint"]["sheared"]
    assert sheared_record["strokes"][0]["region"] == {
        "kind": "affine",
        "region": sheared_top,
        "object_to_world": sheared,
    }


def test_named_layer_requires_a_nonblank_name_and_at_least_one_stroke(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    blank = paint(
        api_client,
        actor,
        version_id,
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
        layer_name="   ",
    )
    assert blank.status_code == 422
    empty = paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[],
        layer_name="Base",
    )
    assert empty.status_code == 422


def test_material_brush_resolves_the_catalogue_and_embeds_pbr_evidence(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    import trimesh

    material_id = "interior.concrete.architectural-light.v1"
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(
        api_client,
        actor,
        version_id,
        strokes=[{"catalog_material_id": material_id, "opacity": 0.85, "region": TOP_FACE}],
        layer_name="Concrete accent",
    )
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["paint"]["materials"] == [material_id]
    made = db_session.get(ProjectVersion, result["version_id"])
    assert made is not None
    assert made.provenance["paint"]["strokes"] == [
        {"catalog_material_id": material_id, "opacity": 0.85, "region": TOP_FACE}
    ]
    preview_id = {link.role: link.asset_id for link in made.assets}[AssetRole.preview]
    preview = db_session.get(Asset, preview_id)
    assert preview is not None
    loaded = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    pbr = next(
        material
        for geometry in loaded.geometry.values()
        if (material := getattr(geometry.visual, "material", None)) is not None
        and material.name == material_id
    )
    assert pbr.baseColorTexture is not None
    assert pbr.metallicRoughnessTexture is not None
    assert pbr.alphaMode == "OPAQUE"
    assert pbr.metallicFactor == pytest.approx(1.0)
    assert pbr.roughnessFactor == pytest.approx(1.0)
    assert np.all(np.asarray(pbr.baseColorTexture.convert("RGBA"))[..., 3] == 255)

    assert (
        paint(
            api_client,
            actor,
            version_id,
            strokes=[{"catalog_material_id": "unknown.material"}],
        ).status_code
        == 422
    )
    assert (
        paint(
            api_client,
            actor,
            version_id,
            strokes=[{"catalog_material_id": material_id, "colour": "#ffffff"}],
        ).status_code
        == 422
    )


def test_partial_untextured_material_replays_over_saved_pbr_layer(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Reference 77: saved untextured PBR layers blend base, roughness and metallic."""
    import trimesh

    version_id = imported_version(api_client, actor, db_session, storage, project)
    base_id = "interior.metal.steel.v1"
    base = paint(
        api_client,
        actor,
        version_id,
        strokes=[{"catalog_material_id": base_id}],
        layer_name="Metal base",
    )
    assert base.status_code == 202, base.text
    (base_job,) = run_all(db_session, storage)
    assert base_job.status is JobStatus.succeeded, base_job.error

    finish_id = "interior.paint.warm-white-matte.v1"
    finish = paint(
        api_client,
        actor,
        str((base_job.result or {})["version_id"]),
        strokes=[{"catalog_material_id": finish_id, "opacity": 0.25}],
        layer_name="White finish",
    )
    assert finish.status_code == 202, finish.text
    (finish_job,) = run_all(db_session, storage)
    assert finish_job.status is JobStatus.succeeded, finish_job.error

    result = finish_job.result or {}
    made = db_session.get(ProjectVersion, result["version_id"])
    assert made is not None
    assert [layer["name"] for layer in made.provenance["paint"]["layers"]] == [
        "Metal base",
        "White finish",
    ]
    assert [stroke["catalog_material_id"] for stroke in made.provenance["paint"]["strokes"]] == [
        base_id,
        finish_id,
    ]
    preview_id = {link.role: link.asset_id for link in made.assets}[AssetRole.preview]
    preview = db_session.get(Asset, preview_id)
    assert preview is not None
    loaded = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    pbr = next(
        material
        for geometry in loaded.geometry.values()
        if (material := getattr(geometry.visual, "material", None)) is not None
        and material.name == finish_id
    )
    base_texture = np.asarray(pbr.baseColorTexture.convert("RGBA"))
    pbr_texture = np.asarray(pbr.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(base_texture[base_texture[..., :3].any(axis=2), :3], axis=0),
        [[187, 190, 191]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(pbr_texture[pbr_texture[..., 2] > 0, 1:3], axis=0),
        [[139, 191]],
        atol=1,
    )

    colour = paint(
        api_client,
        actor,
        str(result["version_id"]),
        strokes=[{"colour": "#0000ff", "opacity": 0.5}],
        layer_name="Blue glaze",
    )
    assert colour.status_code == 202, colour.text
    (colour_job,) = run_all(db_session, storage)
    assert colour_job.status is JobStatus.succeeded, colour_job.error

    colour_result = colour_job.result or {}
    assert colour_result["paint"]["materials"] == [base_id, finish_id]
    coloured = db_session.get(ProjectVersion, colour_result["version_id"])
    assert coloured is not None
    assert [layer["name"] for layer in coloured.provenance["paint"]["layers"]] == [
        "Metal base",
        "White finish",
        "Blue glaze",
    ]
    assert coloured.provenance["paint"]["strokes"][-1] == {
        "colour": "#0000ff",
        "opacity": 0.5,
    }
    coloured_preview_id = {link.role: link.asset_id for link in coloured.assets}[AssetRole.preview]
    coloured_preview = db_session.get(Asset, coloured_preview_id)
    assert coloured_preview is not None
    coloured_scene = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(coloured_preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    colour_pbr = next(
        material
        for geometry in coloured_scene.geometry.values()
        if (material := getattr(geometry.visual, "material", None)) is not None
        and material.name == "paint:colour-composite:0000FF"
    )
    colour_base = np.asarray(colour_pbr.baseColorTexture.convert("RGBA"))
    colour_channels = np.asarray(colour_pbr.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(colour_base[colour_base[..., :3].any(axis=2), :3], axis=0),
        [[94, 95, 223]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(colour_channels[colour_channels[..., 2] > 0, 1:3], axis=0),
        [[197, 96]],
        atol=1,
    )


def test_bounded_partial_stack_replays_one_saved_textured_underlay(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Reference 77: one trusted texture can feed a bounded multi-layer PBR stack."""
    import trimesh

    version_id = imported_version(api_client, actor, db_session, storage, project)
    underlay_id = "interior.concrete.architectural-light.v1"
    underlay = paint(
        api_client,
        actor,
        version_id,
        strokes=[{"catalog_material_id": underlay_id}],
        layer_name="Concrete base",
    )
    assert underlay.status_code == 202, underlay.text
    (underlay_job,) = run_all(db_session, storage)
    assert underlay_job.status is JobStatus.succeeded, underlay_job.error

    finish_id = "interior.metal.steel.v1"
    finish = paint(
        api_client,
        actor,
        str((underlay_job.result or {})["version_id"]),
        strokes=[{"catalog_material_id": finish_id, "opacity": 0.5}],
        layer_name="Steel finish",
    )
    assert finish.status_code == 202, finish.text
    (finish_job,) = run_all(db_session, storage)
    assert finish_job.status is JobStatus.succeeded, finish_job.error

    result = finish_job.result or {}
    assert result["paint"]["materials"] == [underlay_id, finish_id]
    made = db_session.get(ProjectVersion, result["version_id"])
    assert made is not None
    preview_id = {link.role: link.asset_id for link in made.assets}[AssetRole.preview]
    preview = db_session.get(Asset, preview_id)
    assert preview is not None
    loaded = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    pbr = next(
        material
        for geometry in loaded.geometry.values()
        if (material := getattr(geometry.visual, "material", None)) is not None
        and material.name == finish_id
    )
    base = np.asarray(pbr.baseColorTexture.convert("RGBA"))
    channels = np.asarray(pbr.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(base[base[..., :3].any(axis=2), :3], axis=0),
        [[146, 148, 147]],
        atol=1,
    )
    assert np.all(base[..., 3] == 255)
    np.testing.assert_allclose(
        np.unique(channels[channels[..., 2] > 0, 1:3], axis=0),
        [[171, 128]],
        atol=1,
    )

    colour = paint(
        api_client,
        actor,
        str(result["version_id"]),
        strokes=[{"colour": "#0000ff", "opacity": 0.5}],
        layer_name="Blue glaze",
    )
    assert colour.status_code == 202, colour.text
    (colour_job,) = run_all(db_session, storage)
    assert colour_job.status is JobStatus.succeeded, colour_job.error

    colour_result = colour_job.result or {}
    assert colour_result["paint"]["materials"] == [underlay_id, finish_id]
    coloured = db_session.get(ProjectVersion, colour_result["version_id"])
    assert coloured is not None
    assert [layer["name"] for layer in coloured.provenance["paint"]["layers"]] == [
        "Concrete base",
        "Steel finish",
        "Blue glaze",
    ]
    colour_preview_id = {link.role: link.asset_id for link in coloured.assets}[AssetRole.preview]
    colour_preview = db_session.get(Asset, colour_preview_id)
    assert colour_preview is not None
    colour_scene = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(colour_preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    colour_pbr = next(
        material
        for geometry in colour_scene.geometry.values()
        if (material := getattr(geometry.visual, "material", None)) is not None
        and material.name == "paint:colour-composite:0000FF"
    )
    colour_base = np.asarray(colour_pbr.baseColorTexture.convert("RGBA"))
    colour_channels = np.asarray(colour_pbr.metallicRoughnessTexture.convert("RGBA"))
    np.testing.assert_allclose(
        np.unique(colour_base[colour_base[..., :3].any(axis=2), :3], axis=0),
        [[73, 74, 201]],
        atol=1,
    )
    np.testing.assert_allclose(
        np.unique(colour_channels[colour_channels[..., 1] > 0, 1:3], axis=0),
        [[213, 64]],
        atol=1,
    )


def test_workspace_image_upload_is_a_hash_checked_custom_paint_texture(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Reference 77: an authorized immutable PNG can be replayed as a bounded PBR stroke."""
    import trimesh
    from PIL import Image

    image = Image.new("RGBA", (2, 2))
    image.putdata([(255, 0, 0, 255), (0, 255, 0, 255)] * 2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    texture_asset_id = upload(api_client, actor, payload, "paint-texture.png", "image/png")
    version_id = imported_version(api_client, actor, db_session, storage, project)
    stroke = {
        "custom_texture_asset_id": texture_asset_id,
        "custom_texture_tile_size_mm": 125,
        "custom_texture_roughness": 0.35,
        "custom_texture_metallic": 0.1,
        "opacity": 0.75,
    }

    response = paint(
        api_client,
        actor,
        version_id,
        strokes=[stroke],
        layer_name="Uploaded weave",
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    made = db_session.get(ProjectVersion, result["version_id"])
    assert made is not None
    assert made.provenance["paint"]["strokes"] == [stroke]
    custom_material_id = f"workspace.texture.{texture_asset_id}"
    assert result["paint"]["materials"] == [custom_material_id]
    preview_id = {link.role: link.asset_id for link in made.assets}[AssetRole.preview]
    preview = db_session.get(Asset, preview_id)
    assert preview is not None
    loaded = trimesh.load(
        trimesh.util.wrap_as_stream(storage.get(preview.storage_key)),
        file_type="glb",
        force="scene",
        process=False,
    )
    material = next(
        geometry.visual.material
        for geometry in loaded.geometry.values()
        if geometry.visual.material.name == custom_material_id
    )
    assert material.baseColorTexture is not None
    assert material.metallicRoughnessTexture is not None
    assert material.alphaMode == "OPAQUE"

    stranger = make_actor(db_session)
    foreign_asset_id = upload(api_client, stranger, payload, "foreign.png", "image/png")
    foreign = paint(
        api_client,
        actor,
        version_id,
        strokes=[{**stroke, "custom_texture_asset_id": foreign_asset_id}],
        layer_name="Foreign",
    )
    assert foreign.status_code == 422
    assert foreign.json()["error"]["message"] == "custom paint texture is unavailable"
    assert (
        paint(
            api_client,
            actor,
            version_id,
            strokes=[{"custom_texture_asset_id": texture_asset_id}],
            layer_name="Incomplete",
        ).status_code
        == 422
    )


def test_reordering_paint_layers_changes_which_colour_wins_the_overlap(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Reference 77: compositing is last-stroke-wins, so layer order is a real visual choice."""
    import trimesh
    from worker.importers.common import as_single_mesh

    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(
        api_client,
        actor,
        version_id,
        strokes=[{"colour": "#ff0000", "region": TOP_FACE}],
        layer_name="Red",
    )
    (first,) = run_all(db_session, storage)
    assert first.status is JobStatus.succeeded, first.error
    red_on_top = str((first.result or {})["version_id"])

    paint(
        api_client,
        actor,
        red_on_top,
        strokes=[{"colour": "#0000ff", "region": TOP_FACE}],
        layer_name="Blue",
    )
    (second,) = run_all(db_session, storage)
    assert second.status is JobStatus.succeeded, second.error
    blue_on_top = db_session.get(ProjectVersion, (second.result or {})["version_id"])
    assert blue_on_top is not None
    assert [layer["name"] for layer in blue_on_top.provenance["paint"]["layers"]] == ["Red", "Blue"]

    def top_face_colours(version: ProjectVersion) -> set[tuple[int, int, int]]:
        preview_asset_id = {link.role: link.asset_id for link in version.assets}[AssetRole.preview]
        preview = db_session.get(Asset, preview_asset_id)
        assert preview is not None
        data = storage.get(preview.storage_key)
        loaded = as_single_mesh(
            trimesh.load(io.BytesIO(data), file_type="glb", force="mesh", process=False)
        )
        assert loaded is not None
        return {tuple(int(c) for c in colour[:3]) for colour in loaded.visual.face_colors}

    assert (0, 0, 255) in top_face_colours(blue_on_top)  # Blue painted last, wins the overlap

    reordered = reorder(api_client, actor, str(blue_on_top.id), ["Blue", "Red"])
    assert reordered.status_code == 202, reordered.text
    (third,) = run_all(db_session, storage)
    assert third.status is JobStatus.succeeded, third.error
    final = db_session.get(ProjectVersion, (third.result or {})["version_id"])
    assert final is not None
    assert [layer["name"] for layer in final.provenance["paint"]["layers"]] == ["Blue", "Red"]
    assert [s["colour"] for s in final.provenance["paint"]["strokes"]] == ["#0000ff", "#ff0000"]
    assert (255, 0, 0) in top_face_colours(final)  # Red now painted last, wins the overlap


def test_reorder_rejects_missing_layers_bad_permutation_and_gaps(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)

    no_layers = reorder(api_client, actor, version_id, ["Anything"])
    assert no_layers.status_code == 422
    assert "no named paint layers" in no_layers.json()["error"]["message"]

    paint(
        api_client,
        actor,
        version_id,
        strokes=[{"colour": "#ff0000", "region": TOP_FACE}],
        layer_name="Red",
    )
    (first,) = run_all(db_session, storage)
    assert first.status is JobStatus.succeeded, first.error
    red_only = str((first.result or {})["version_id"])

    # An unnamed stroke after the named layer leaves a gap in the coverage.
    paint(api_client, actor, red_only, strokes=[{"colour": "#00ff00"}])
    (second,) = run_all(db_session, storage)
    assert second.status is JobStatus.succeeded, second.error
    gapped = str((second.result or {})["version_id"])
    gapped_response = reorder(api_client, actor, gapped, ["Red"])
    assert gapped_response.status_code == 422
    assert "every stroke must belong" in gapped_response.json()["error"]["message"]

    paint(
        api_client,
        actor,
        red_only,
        strokes=[{"colour": "#0000ff", "region": TOP_FACE}],
        layer_name="Blue",
    )
    (third,) = run_all(db_session, storage)
    assert third.status is JobStatus.succeeded, third.error
    fully_named = str((third.result or {})["version_id"])

    assert reorder(api_client, actor, fully_named, ["Red", "Green"]).status_code == 422
    assert reorder(api_client, actor, fully_named, ["Red"]).status_code == 422
    assert reorder(api_client, actor, fully_named, ["Red", "Red"]).status_code == 422
    assert reorder(api_client, actor, fully_named, ["Red", " " * 81]).status_code == 422

    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    assert reorder(api_client, viewer, fully_named, ["Blue", "Red"]).status_code == 403

    stranger = make_actor(db_session)
    assert reorder(api_client, stranger, fully_named, ["Blue", "Red"]).status_code == 404


def test_painting_a_painted_version_keeps_the_earlier_strokes(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Paint accumulates: the second stroke does not wipe the first (F-034)."""
    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
    )
    (first,) = run_all(db_session, storage)
    assert first.status is JobStatus.succeeded, first.error
    painted_once = str((first.result or {})["version_id"])

    side = {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [30, 20, 3]}
    paint(api_client, actor, painted_once, strokes=[{"colour": "#5b9cff", "region": side}])
    (second,) = run_all(db_session, storage)
    assert second.status is JobStatus.succeeded, second.error
    report = (second.result or {})["paint"]
    assert {"#202020", "#ff5533", "#5b9cff"} <= set(report["colours"])

    twice = db_session.get(ProjectVersion, (second.result or {})["version_id"])
    assert twice is not None
    assert [s["colour"] for s in twice.provenance["paint"]["strokes"]] == [
        "#ff5533",
        "#5b9cff",
    ]
    assert twice.provenance["paint"]["base_colour"] == "#202020"

    # ...unless the caller asks to start from the bare model.
    paint(
        api_client,
        actor,
        str(twice.id),
        strokes=[{"colour": "#35c48d"}],
        replace=True,
    )
    (third,) = run_all(db_session, storage)
    assert third.status is JobStatus.succeeded, third.error
    fresh = db_session.get(ProjectVersion, (third.result or {})["version_id"])
    assert fresh is not None
    assert [s["colour"] for s in fresh.provenance["paint"]["strokes"]] == ["#35c48d"]


def test_a_painted_version_keeps_its_parametric_history(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """Paint on a kernel-built part, then keep editing it: the history survives the paint."""
    import sqlalchemy as sa
    from worker import geometry as kernel

    from app.models.execution import Operation

    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 40x30x6 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    built_id = str((built.result or {})["version_id"])

    paint(
        api_client,
        actor,
        built_id,
        strokes=[{"colour": "#ff5533"}],
        layer_name="Primary finish",
    )
    (painted_job,) = run_all(db_session, storage)
    assert painted_job.status is JobStatus.succeeded, painted_job.error
    painted_id = str((painted_job.result or {})["version_id"])

    def operations(version_id: str) -> list[tuple[int, str]]:
        rows = db_session.scalars(
            sa.select(Operation)
            .where(Operation.project_version_id == version_id)
            .order_by(Operation.sequence_no)
        ).all()
        return [(row.sequence_no, row.operation_type) for row in rows]

    assert operations(painted_id) == operations(built_id) != []
    painted = db_session.get(ProjectVersion, painted_id)
    assert painted is not None
    roles = {link.role for link in painted.assets}
    assert {AssetRole.model, AssetRole.source, AssetRole.preview} <= roles  # BREP kept
    bodies = painted.provenance.get("bodies")
    assert bodies  # the kernel bodies, for targeting
    target = bodies[-1]["name"]

    # The editor works on the painted version like on any other.
    response = api_client.post(
        f"/api/v1/models/{painted_id}/edits",
        json={
            "operations": [{"type": "set_dimensions", "target": target, "width_mm": 50}],
            "label": "Wider",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (edited,) = run_all(db_session, storage)
    assert edited.status is JobStatus.succeeded, edited.error
    if kernel.available():  # the real kernel actually rescales the body
        size = (edited.result or {})["bodies"][-1]["bbox_mm"]["size"]
        assert size[0] == pytest.approx(50, abs=0.01)

    # T-115: the edit carried the paint onto the new shape — a preview and the strokes.
    wider = db_session.get(ProjectVersion, (edited.result or {})["version_id"])
    assert wider is not None
    assert AssetRole.preview in {link.role for link in wider.assets}
    carried = wider.provenance["paint"]
    assert [s["colour"] for s in carried["strokes"]] == ["#ff5533"]
    assert carried["layers"] == [{"name": "Primary finish", "stroke_start": 0, "stroke_count": 1}]
    assert carried["carried_from"] == painted_id
    assert carried["report"]["painted_faces"] > 0
    assert (edited.result or {})["paint"]["painted_faces"] > 0

    # ...and the paint keeps accumulating on the edited version.
    paint(api_client, actor, str(wider.id), strokes=[{"colour": "#5b9cff"}])
    (again,) = run_all(db_session, storage)
    assert again.status is JobStatus.succeeded, again.error
    twice = db_session.get(ProjectVersion, (again.result or {})["version_id"])
    assert twice is not None
    assert [s["colour"] for s in twice.provenance["paint"]["strokes"]] == ["#ff5533", "#5b9cff"]


def test_paint_that_no_longer_lands_after_an_edit_is_reported_not_hidden(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    """A stroke on a corner that the edit cuts away is lost — and the provenance says so."""
    response = api_client.post(
        f"/api/v1/projects/{project}/ai-commands",
        json={"prompt": "Plate 40x30x6 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (built,) = run_all(db_session, storage)
    assert built.status is JobStatus.succeeded, built.error
    built_id = str((built.result or {})["version_id"])
    built_version = db_session.get(ProjectVersion, built_id)
    assert built_version is not None
    target = built_version.provenance["bodies"][-1]["name"]

    # paint only the far end of the plate (x from 35 to 40)
    far_end = {"kind": "box", "min_mm": [35, -1, -1], "max_mm": [41, 31, 7]}
    paint(api_client, actor, built_id, strokes=[{"colour": "#ff5533", "region": far_end}])
    (painted_job,) = run_all(db_session, storage)
    assert painted_job.status is JobStatus.succeeded, painted_job.error
    painted_id = str((painted_job.result or {})["version_id"])

    # ...then make the plate shorter than the painted end
    response = api_client.post(
        f"/api/v1/models/{painted_id}/edits",
        json={
            "operations": [{"type": "set_dimensions", "target": target, "width_mm": 20}],
            "label": "Shorter",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (edited,) = run_all(db_session, storage)
    assert edited.status is JobStatus.succeeded, edited.error
    shorter = db_session.get(ProjectVersion, (edited.result or {})["version_id"])
    assert shorter is not None
    carried = shorter.provenance["paint"]
    assert carried["strokes"][0]["colour"] == "#ff5533"  # kept for the record
    from worker import geometry as kernel

    if kernel.available():  # the fake kernel does not resize, so the stroke still lands
        assert carried.get("lost")
        assert carried["report"]["painted_faces"] == 0
        assert AssetRole.preview not in {link.role for link in shorter.assets}


def test_a_stroke_that_misses_the_model_says_so(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    miss = {
        "kind": "box",
        "min_mm": [500, 500, 500],
        "max_mm": [510, 510, 510],
    }
    paint(api_client, actor, version_id, strokes=[{"colour": "#00ff00", "region": miss}])
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "nothing_painted"


def test_painting_a_whole_body_needs_no_region(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(api_client, actor, version_id, strokes=[{"colour": "#1188ff"}])
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    report = (job.result or {})["paint"]
    assert report["painted_faces"] == report["faces"]  # all of it


def test_an_empty_paint_request_is_refused(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(api_client, actor, version_id)
    assert response.status_code == 422
    assert "nothing to paint" in response.json()["error"]["message"]


def test_a_bad_colour_is_refused_before_the_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(api_client, actor, version_id, strokes=[{"colour": "red"}])
    assert response.status_code == 422


def test_the_worker_and_the_api_agree_on_the_region_shape() -> None:
    """Both sides parse the same JSON; the worker never imports the API to do it."""
    from worker.paint import BoxRegion as WorkerBox
    from worker.paint import LassoRegion as WorkerLasso

    from app.geometry.region import BoxRegion as ApiBox
    from app.geometry.region import LassoRegion as ApiLasso

    box = {"kind": "box", "min_mm": [0, 0, 0], "max_mm": [1, 2, 3]}
    lasso = TOP_FACE
    assert ApiBox.model_validate(box).model_dump() == WorkerBox.model_validate(box).model_dump()
    api_lasso = ApiLasso.model_validate(lasso).model_dump()
    worker_lasso = WorkerLasso.model_validate(lasso).model_dump()
    assert api_lasso == worker_lasso


@pytest.mark.parametrize("target", ["glb", "ply", "obj", "3mf"])
def test_painted_colours_survive_export(target: str) -> None:
    """A colour-carrying format must actually carry the colours out (F-014).

    PLY stores a colour per face; glTF and OBJ store colour per vertex, so the painter
    gives every face its own vertices — the colours come back exactly, with no blends.
    """
    import tempfile
    from pathlib import Path

    import trimesh
    from worker.paint import LassoRegion, PaintRequest, Stroke, paint_file

    tmp = Path(tempfile.mkdtemp())
    mesh = trimesh.creation.box(extents=(30, 20, 10))
    mesh.apply_translation([15, 10, 5])
    source = tmp / "box.stl"
    source.write_bytes(mesh.export(file_type="stl"))

    request = PaintRequest(
        base_colour="#202020",
        strokes=[Stroke(colour="#ff5533", region=LassoRegion.model_validate(TOP_FACE))],
    )
    output = tmp / f"painted.{target}"
    result = paint_file(source, "stl", request, output, target)
    assert result.ok and result.painted_faces > 0

    if target == "3mf":
        namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        with zipfile.ZipFile(output) as archive:
            model = etree.fromstring(archive.read("3D/3dmodel.model"))
        materials = model.find(f"{namespace}resources/{namespace}basematerials")
        assert materials is not None
        assert {base.get("displaycolor") for base in materials} == {"#FF5533", "#202020"}
        triangles = list(model.iter(f"{namespace}triangle"))
        assert triangles
        assert {triangle.get("pid") for triangle in triangles} == {materials.get("id")}
        assert {triangle.get("p1") for triangle in triangles} == {"0", "1"}
        assert all(
            triangle.get("p2") is None and triangle.get("p3") is None for triangle in triangles
        )
        return

    from worker.importers.common import as_single_mesh

    # process=False: the loader would otherwise merge the per-face vertices back together
    loaded = as_single_mesh(trimesh.load(output, force="mesh", process=False))
    assert loaded is not None
    visual = loaded.visual
    assert visual is not None and hasattr(visual, "face_colors")
    colours = {tuple(colour[:3]) for colour in visual.face_colors}
    assert colours == {(255, 85, 51), (32, 32, 32)}  # the stroke and the base, nothing between


def test_a_standard_3mf_export_of_a_painted_version_keeps_discrete_colours(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
    )
    assert response.status_code == 202, response.text
    (painted_job,) = run_all(db_session, storage)
    assert painted_job.status is JobStatus.succeeded, painted_job.error
    painted_id = str((painted_job.result or {})["version_id"])
    painted_version = db_session.get(ProjectVersion, painted_id)
    assert painted_version is not None
    preview_id = {link.role: link.asset_id for link in painted_version.assets}[AssetRole.preview]

    accepted = api_client.post(
        f"/api/v1/models/{painted_id}/exports",
        json={"format": "3mf"},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (export_job,) = run_all(db_session, storage)
    assert export_job.status is JobStatus.succeeded, export_job.error
    assert (export_job.input or {})["asset_id"] == str(preview_id)
    result = export_job.result or {}
    assert result["report"]["paint_handoff"] == {
        "carried": True,
        "encoding": "3mf_core_basematerials",
        "source_asset_id": str(preview_id),
    }
    exported = db_session.get(Asset, result["asset_id"])
    assert exported is not None and exported.format == "3mf"

    namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    with zipfile.ZipFile(io.BytesIO(storage.get(exported.storage_key))) as archive:
        model = etree.fromstring(archive.read("3D/3dmodel.model"))
    materials = model.find(f"{namespace}resources/{namespace}basematerials")
    assert materials is not None
    assert {base.get("displaycolor") for base in materials} == {"#FF5533", "#202020"}
    triangles = list(model.iter(f"{namespace}triangle"))
    assert {triangle.get("p1") for triangle in triangles} == {"0", "1"}


@pytest.mark.parametrize("target", ["glb", "ply"])
def test_a_standard_colour_export_of_a_painted_version_uses_the_coloured_preview(
    target: str,
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    import trimesh
    from worker.importers.common import as_single_mesh

    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = paint(
        api_client,
        actor,
        version_id,
        base_colour="#202020",
        strokes=[{"colour": "#ff5533", "region": TOP_FACE}],
    )
    assert response.status_code == 202, response.text
    (painted_job,) = run_all(db_session, storage)
    assert painted_job.status is JobStatus.succeeded, painted_job.error
    painted_id = str((painted_job.result or {})["version_id"])
    painted_version = db_session.get(ProjectVersion, painted_id)
    assert painted_version is not None
    preview_id = {link.role: link.asset_id for link in painted_version.assets}[AssetRole.preview]

    accepted = api_client.post(
        f"/api/v1/models/{painted_id}/exports",
        json={"format": target},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (export_job,) = run_all(db_session, storage)
    assert export_job.status is JobStatus.succeeded, export_job.error
    assert (export_job.input or {})["asset_id"] == str(preview_id)
    exported = db_session.get(Asset, (export_job.result or {})["asset_id"])
    assert exported is not None and exported.format == target

    loaded = as_single_mesh(
        trimesh.load(io.BytesIO(storage.get(exported.storage_key)), file_type=target, process=False)
    )
    assert loaded is not None
    colours = {tuple(colour[:3]) for colour in loaded.visual.face_colors}
    assert colours == {(255, 85, 51), (32, 32, 32)}


def test_a_game_export_of_a_painted_version_bakes_the_paint(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    paint(api_client, actor, version_id, strokes=[{"colour": "#1188ff", "region": TOP_FACE}])
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    painted = str((job.result or {})["version_id"])
    accepted = api_client.post(
        f"/api/v1/models/{painted}/exports",
        json={"format": "glb", "game": {"name": "Crate", "texture_px": 256}},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (export,) = run_all(db_session, storage)
    assert export.status is JobStatus.succeeded, export.error
    assert (export.result or {})["report"]["baked_texture_px"] == 256
