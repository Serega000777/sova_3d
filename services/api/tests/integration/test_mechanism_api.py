"""F-037/F-038: a generated hinge is real scene geometry with a bounded joint."""

from __future__ import annotations

import json
import struct
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.models.versioning import Asset
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

    scene = api_client.get(
        f"/api/v1/models/{result['version_id']}/scene", headers=actor.headers
    )
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
