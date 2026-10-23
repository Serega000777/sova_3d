"""F-019/F-064: calibrated references persist with project access control."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, WorkspaceMember
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.versioning import AssetKind
from tests.integration.conftest import Actor, make_actor


def _image_asset(db: Session, actor: Actor, digit: str = "a") -> Asset:
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256=digit * 64,
        storage_key=f"ws/{actor.workspace.id}/assets/{digit * 64}.jpg",
        mime="image/jpeg",
        format="jpeg",
        byte_size=1024,
    )
    db.add(asset)
    db.flush()
    return asset


def _body(asset: Asset) -> dict[str, Any]:
    return {
        "asset_id": str(asset.id),
        "width_px": 1200,
        "height_px": 800,
        "width_mm": 240,
        "known_mm": 20,
        "calibration": [[0.2, 0.5], [0.3, 0.5]],
        "measurements": [
            {
                "id": "10000000-0000-4000-8000-000000000001",
                "label": "Window width",
                "points": [[0.4, 0.3], [0.7, 0.3]],
            }
        ],
        "offset_x": 5,
        "offset_z": -3,
        "opacity": 0.6,
        "visible": True,
    }


def test_reference_roundtrip_and_workspace_boundary(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Photo part"},
        headers=actor.headers,
    ).json()["id"]
    path = f"/api/v1/projects/{project_id}/reference"
    assert api_client.get(path, headers=actor.headers).json() is None

    asset = _image_asset(db_session, actor)
    saved = api_client.put(path, json=_body(asset), headers=actor.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["asset_id"] == str(asset.id)
    assert saved.json()["calibration"] == [[0.2, 0.5], [0.3, 0.5]]
    assert saved.json()["measurements"][0]["label"] == "Window width"
    assert saved.json()["url"]
    assert api_client.get(path, headers=actor.headers).json()["width_mm"] == 240

    foreign = make_actor(db_session)
    assert api_client.get(path, headers=foreign.headers).status_code == 404
    foreign_asset = _image_asset(db_session, foreign, "b")
    assert api_client.put(path, json=_body(foreign_asset), headers=actor.headers).status_code == 404
    bad_calibration = {**_body(asset), "calibration": [[-0.1, 0.5]]}
    assert api_client.put(path, json=bad_calibration, headers=actor.headers).status_code == 422
    duplicate_measurement = _body(asset)
    duplicate_measurement["measurements"] = [
        duplicate_measurement["measurements"][0],
        duplicate_measurement["measurements"][0],
    ]
    assert (
        api_client.put(path, json=duplicate_measurement, headers=actor.headers).status_code == 422
    )

    non_image = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256="c" * 64,
        storage_key=f"ws/{actor.workspace.id}/assets/{'c' * 64}.stl",
        mime="model/stl",
        format="stl",
        byte_size=100,
    )
    db_session.add(non_image)
    db_session.flush()
    assert api_client.put(path, json=_body(non_image), headers=actor.headers).status_code == 422

    db_session.add(
        WorkspaceMember(
            workspace_id=actor.workspace.id,
            user_id=foreign.user.id,
            role=WorkspaceRole.viewer,
        )
    )
    db_session.flush()
    assert api_client.get(path, headers=foreign.headers).status_code == 200
    assert api_client.put(path, json=_body(asset), headers=foreign.headers).status_code == 403
    assert api_client.delete(path, headers=foreign.headers).status_code == 403

    updated = api_client.put(path, json={**_body(asset), "opacity": 0.9}, headers=actor.headers)
    assert updated.status_code == 200 and updated.json()["opacity"] == 0.9
    assert api_client.delete(path, headers=actor.headers).status_code == 204
    assert api_client.get(path, headers=actor.headers).json() is None


def test_dimensioned_drawing_requires_calibrated_reference_and_queues_exact_plan(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    project_id = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "Dimensioned drawing"},
        headers=actor.headers,
    ).json()["id"]
    endpoint = f"/api/v1/projects/{project_id}/dimensioned-drawing"
    trace = {
        "width_mm": 100,
        "height_mm": 60,
        "thickness_mm": 8,
        "corner_radius_mm": 10,
        "holes": [
            {"x_mm": -25, "y_mm": 0, "diameter_mm": 10},
            {"x_mm": 25, "y_mm": 0, "diameter_mm": 8},
        ],
    }
    missing = api_client.post(endpoint, json=trace, headers=actor.headers)
    assert missing.status_code == 409

    asset = _image_asset(db_session, actor, "d")
    saved = api_client.put(
        f"/api/v1/projects/{project_id}/reference",
        json=_body(asset),
        headers=actor.headers,
    )
    assert saved.status_code == 200, saved.text
    accepted = api_client.post(endpoint, json=trace, headers=actor.headers)
    assert accepted.status_code == 202, accepted.text
    job = db_session.get(Job, accepted.json()["job_id"])
    assert job is not None
    assert job.input["provenance"]["created_with"] == "dimensioned_drawing_trace"
    assert job.input["provenance"]["drawing_trace"]["source_asset_id"] == str(asset.id)
    assert [operation["type"] for operation in job.input["plan"]["operations"]] == [
        "extrude",
        "add_hole",
        "add_hole",
    ]

    crossing = api_client.post(
        endpoint,
        json={**trace, "holes": [{"x_mm": 48, "y_mm": 0, "diameter_mm": 10}]},
        headers=actor.headers,
    )
    assert crossing.status_code == 422
    overlapping = api_client.post(
        endpoint,
        json={
            **trace,
            "holes": [
                {"x_mm": 0, "y_mm": 0, "diameter_mm": 10},
                {"x_mm": 5, "y_mm": 0, "diameter_mm": 10},
            ],
        },
        headers=actor.headers,
    )
    assert overlapping.status_code == 422
