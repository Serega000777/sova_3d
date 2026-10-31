"""F-037/F-038: generated mechanisms are real scene geometry with one bounded joint."""

from __future__ import annotations

import json
import struct
import uuid
from io import BytesIO
from typing import Any

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.models.versioning import Asset, ProjectVersion
from app.services.scene_animations import mechanism_animation
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_engineering_api import built_version
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def test_hinged_lid_builds_three_parts_and_a_revolute_joint(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id, _ = built_version(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/models/{source_id}/mechanisms/hinged-lid",
        json={
            "width_mm": 100,
            "depth_mm": 70,
            "base_height_mm": 18,
            "lid_thickness_mm": 4,
            "pin_diameter_mm": 4,
            "clearance_mm": 0.3,
            "max_angle_deg": 110,
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert set(result["asset_ids"]) == {"base", "lid", "pin"}
    mechanism = result["mechanism"]
    assert mechanism["joint"] == {
        "type": "revolute",
        "node_id": mechanism["parts"]["lid"],
        "axis": "x",
        "pivot_mm": [0, 0, 18.0],
        "min_angle_deg": 0,
        "max_angle_deg": 110.0,
    }
    assert mechanism["validation"]["strength_claim"] is False

    scene = api_client.get(f"/api/v1/models/{result['version_id']}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert all(nodes[node_id]["effective_visible"] for node_id in mechanism["parts"].values())
    lid = nodes[mechanism["parts"]["lid"]]
    assert lid["transform"][2][3] == 18

    export = api_client.post(
        f"/api/v1/models/{result['version_id']}/exports",
        json={"format": "glb"},
        headers=actor.headers,
    )
    assert export.status_code == 202, export.text
    (export_job,) = run_all(db_session, storage)
    assert export_job.status is JobStatus.succeeded, export_job.error
    export_result = export_job.result or {}
    assert export_result["report"]["scene"]["animations"] == 1
    asset = db_session.get(Asset, uuid.UUID(export_result["asset_id"]))
    assert asset is not None
    data = storage.get(asset.storage_key)
    json_length, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    document = json.loads(data[20 : 20 + json_length].rstrip(b" \0"))
    assert document["animations"][0]["name"] == "HingedLid"


@pytest.mark.parametrize("base_height,pin", [(8, 20), (10, 16)])
def test_hinged_lid_refuses_a_hinge_that_does_not_fit_the_base(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    base_height: float,
    pin: float,
) -> None:
    source_id, _ = built_version(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/models/{source_id}/mechanisms/hinged-lid",
        json={"base_height_mm": base_height, "pin_diameter_mm": pin},
        headers=actor.headers,
    )
    assert response.status_code == 422


SLIDING = {
    "width_mm": 100,
    "depth_mm": 70,
    "base_height_mm": 30,
    "wall_mm": 3,
    "floor_mm": 2,
    "lid_thickness_mm": 3,
    "guide_width_mm": 1.5,
    "lip_overhang_mm": 2.5,
    "lip_thickness_mm": 1.5,
    "clearance_mm": 0.3,
    "max_travel_mm": 55,
}


def _glb_document(data: bytes) -> tuple[dict[str, Any], bytes]:
    json_length, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    document = json.loads(data[20 : 20 + json_length].rstrip(b" \0"))
    offset = 20 + json_length
    binary_length, binary_kind = struct.unpack_from("<I4s", data, offset)
    assert binary_kind == b"BIN\0"
    return document, data[offset + 8 : offset + 8 + binary_length]


def test_sliding_lid_builds_two_parts_and_a_prismatic_joint(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    source_id, _ = built_version(api_client, actor, db_session, storage, project)
    before = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers)
    assert before.status_code == 200, before.text
    headers = {**actor.headers, "Idempotency-Key": f"slide-{uuid.uuid4()}"}
    response = api_client.post(
        f"/api/v1/models/{source_id}/mechanisms/sliding-lid", json=SLIDING, headers=headers
    )
    assert response.status_code == 202, response.text
    again = api_client.post(
        f"/api/v1/models/{source_id}/mechanisms/sliding-lid", json=SLIDING, headers=headers
    )
    assert again.status_code == 202 and again.json()["job_id"] == response.json()["job_id"]
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    assert job.type == "build_sliding_lid"
    result = job.result or {}
    assert set(result["asset_ids"]) == {"base", "lid"}
    mechanism = result["mechanism"]
    assert mechanism["kind"] == "sliding_lid"
    assert mechanism["joint"] == {
        "type": "prismatic",
        "node_id": mechanism["parts"]["lid"],
        "axis": "y",
        "origin_mm": [0.0, 3.3, 30.0],
        "min_travel_mm": 0,
        "max_travel_mm": 55.0,
    }
    assert mechanism["validation"]["strength_claim"] is False
    assert "physical validation" in mechanism["validation"]["note"]
    assert mechanism["derived_mm"]["retention_mm"] == pytest.approx(2.2)

    for role, asset_id in result["asset_ids"].items():
        asset = db_session.get(Asset, uuid.UUID(asset_id))
        assert asset is not None and asset.format == "stl", role
        mesh = trimesh.load(BytesIO(storage.get(asset.storage_key)), file_type="stl")
        assert isinstance(mesh, trimesh.Trimesh) and mesh.is_watertight, role

    # the source scene is untouched; the new immutable version carries provenance
    unchanged = api_client.get(f"/api/v1/models/{source_id}/scene", headers=actor.headers)
    assert unchanged.json()["nodes"] == before.json()["nodes"]
    made = db_session.get(ProjectVersion, uuid.UUID(result["version_id"]))
    assert made is not None and made.parent_version_id == uuid.UUID(source_id)
    assert (made.provenance or {})["build_sliding_lid"] == mechanism
    scene = api_client.get(f"/api/v1/models/{result['version_id']}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert {node["id"] for node in before.json()["nodes"]} < set(nodes)
    assert all(nodes[node_id]["effective_visible"] for node_id in mechanism["parts"].values())
    lid = nodes[mechanism["parts"]["lid"]]
    assert [row[3] for row in lid["transform"][:3]] == pytest.approx([0, 3.3, 30])

    export = api_client.post(
        f"/api/v1/models/{result['version_id']}/exports",
        json={"format": "glb"},
        headers=actor.headers,
    )
    assert export.status_code == 202, export.text
    (export_job,) = run_all(db_session, storage)
    assert export_job.status is JobStatus.succeeded, export_job.error
    export_result = export_job.result or {}
    assert export_result["report"]["scene"]["animations"] == 1
    assert export_result["report"]["scene"]["animation_kind"] == "prismatic_joint"
    asset = db_session.get(Asset, uuid.UUID(export_result["asset_id"]))
    assert asset is not None
    document, binary = _glb_document(storage.get(asset.storage_key))
    (animation,) = document["animations"]
    assert animation["name"] == "SlidingLid"
    (channel,) = animation["channels"]
    assert channel["target"]["path"] == "translation"
    accessor = document["accessors"][animation["samplers"][0]["output"]]
    view = document["bufferViews"][accessor["bufferView"]]
    keys = np.frombuffer(
        binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], dtype="<f4"
    ).reshape(2, 3)
    # closed seat (0, 3.3, 30) mm Z-up is (0, 0.030, -0.0033) m Y-up; +55 mm Y is -0.055 m Z
    np.testing.assert_allclose(keys[0], [0, 0.030, -0.0033], atol=1e-6)
    np.testing.assert_allclose(keys[1], [0, 0.030, -0.0583], atol=1e-6)


@pytest.mark.parametrize(
    "change",
    [
        {"guide_width_mm": 2.8},
        {"lip_overhang_mm": 1.0, "clearance_mm": 0.5},
        {"max_travel_mm": 80},
        {"floor_mm": 20, "base_height_mm": 20},
        {"clearance_mm": 0},
    ],
)
def test_sliding_lid_refuses_guides_that_cannot_hold_the_lid(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    change: dict[str, float],
) -> None:
    source_id, _ = built_version(api_client, actor, db_session, storage, project)
    response = api_client.post(
        f"/api/v1/models/{source_id}/mechanisms/sliding-lid",
        json={**SLIDING, **change},
        headers=actor.headers,
    )
    assert response.status_code == 422


HINGE_RECORD: dict[str, Any] = {
    "kind": "hinged_lid",
    "joint": {
        "type": "revolute",
        "node_id": "hinge_lid_a",
        "axis": "x",
        "min_angle_deg": 0,
        "max_angle_deg": 110,
    },
}
SLIDE_RECORD: dict[str, Any] = {
    "kind": "sliding_lid",
    "joint": {
        "type": "prismatic",
        "node_id": "slide_lid_a",
        "axis": "y",
        "min_travel_mm": 0,
        "max_travel_mm": 55,
    },
}


def test_export_animation_picks_the_single_trusted_joint() -> None:
    visible = {"hinge_lid_a", "slide_lid_a"}
    assert mechanism_animation({"build_hinged_lid": HINGE_RECORD}, visible) == {
        "kind": "revolute",
        "node_id": "hinge_lid_a",
        "axis": "x",
        "min_angle_deg": 0.0,
        "max_angle_deg": 110.0,
        "duration_seconds": 1.0,
    }
    assert mechanism_animation({"build_sliding_lid": SLIDE_RECORD}, visible) == {
        "kind": "prismatic",
        "node_id": "slide_lid_a",
        "axis": "y",
        "min_travel_mm": 0.0,
        "max_travel_mm": 55.0,
        "duration_seconds": 1.0,
    }


def _slide(**joint: object) -> dict[str, Any]:
    return {"build_sliding_lid": {**SLIDE_RECORD, "joint": {**SLIDE_RECORD["joint"], **joint}}}


@pytest.mark.parametrize(
    "provenance",
    [
        # ambiguous: one GLB channel must not guess between two mechanisms
        {"build_hinged_lid": HINGE_RECORD, "build_sliding_lid": SLIDE_RECORD},
        # hidden target
        _slide(node_id="slide_lid_hidden"),
        # malformed: wrong type, bad axis, non-finite or inverted range, string numbers
        _slide(type="revolute"),
        _slide(axis="w"),
        _slide(axis="x"),
        _slide(max_travel_mm=float("inf")),
        _slide(max_travel_mm=-5),
        _slide(max_travel_mm="55"),
        {
            "build_hinged_lid": {
                **HINGE_RECORD,
                "joint": {**HINGE_RECORD["joint"], "axis": "y"},
            }
        },
        {"build_sliding_lid": {**SLIDE_RECORD, "kind": "hinged_lid"}},
        {"build_sliding_lid": "slide"},
    ],
)
def test_export_animation_fails_closed(provenance: dict[str, Any]) -> None:
    assert mechanism_animation(provenance, {"hinge_lid_a", "slide_lid_a"}) is None
