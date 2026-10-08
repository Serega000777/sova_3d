"""Paid tools cannot be unlocked by bypassing the web client's lock overlay."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import Actor

MISSING = str(uuid.uuid4())


def assert_pro_required(response: httpx.Response, capability: str) -> None:
    assert response.status_code == 402, response.text
    error = response.json()["error"]
    assert error["code"] == "pro_subscription_required"
    assert error["details"] == {
        "capability": capability,
        "current_plan": "free",
        "required_plan": "pro",
    }


@pytest.mark.parametrize(
    ("path", "body", "capability"),
    [
        (f"/api/v1/models/{MISSING}/reconstruct", {}, "reverse_engineering"),
        (f"/api/v1/models/{MISSING}/engineering", {}, "engineering"),
        (
            "/api/v1/fit-tests",
            {"version_a_id": MISSING, "version_b_id": MISSING},
            "fit_test",
        ),
        (
            f"/api/v1/models/{MISSING}/mesh-edit",
            {
                "operations": [
                    {
                        "op": "detail",
                        "at_mm": [0, 0, 0],
                        "normal_hint": [0, 0, 1],
                        "profile": {"shape": "circle", "diameter_mm": 4},
                        "depth_mm": 1,
                    }
                ]
            },
            "mesh_edit",
        ),
        (f"/api/v1/models/{MISSING}/split", {"parts": 2}, "split_model"),
        (f"/api/v1/models/{MISSING}/exports", {"format": "step"}, "cad_export"),
        (
            f"/api/v1/models/{MISSING}/exports",
            {"format": "glb", "game": {}},
            "game_export",
        ),
        (f"/api/v1/projects/{MISSING}/rollback", {"expression": "v1"}, "history_restore"),
    ],
)
def test_free_cannot_call_paid_endpoints(
    api_client: TestClient,
    free_actor: Actor,
    path: str,
    body: dict[str, object],
    capability: str,
) -> None:
    assert_pro_required(api_client.post(path, json=body, headers=free_actor.headers), capability)


def test_free_operations_allow_holes_but_block_advanced_cad(
    api_client: TestClient, free_actor: Actor
) -> None:
    hole = api_client.post(
        f"/api/v1/models/{MISSING}/edits",
        json={
            "operations": [
                {
                    "type": "add_hole",
                    "target": "body",
                    "face": {"kind": "face_by_normal", "axis": "z"},
                    "position_mm": [0, 0],
                    "diameter_mm": 5,
                }
            ]
        },
        headers=free_actor.headers,
    )
    assert hole.status_code == 404

    advanced = api_client.post(
        f"/api/v1/models/{MISSING}/edits",
        json={
            "operations": [
                {"type": "fillet", "target": "body", "edges": {"kind": "all_edges"}, "radius_mm": 2}
            ]
        },
        headers=free_actor.headers,
    )
    assert advanced.status_code == 402
    details = advanced.json()["error"]["details"]
    assert details["capability"] == "advanced_operations"
    assert details["operations"] == ["fillet"]

    loft = api_client.post(
        f"/api/v1/models/{MISSING}/edits",
        json={
            "operations": [
                {
                    "type": "loft",
                    "sections": [
                        {"profile": {"kind": "circle", "diameter_mm": 10}, "origin_mm": [0, 0, 0]},
                        {"profile": {"kind": "circle", "diameter_mm": 5}, "origin_mm": [0, 0, 10]},
                    ],
                }
            ]
        },
        headers=free_actor.headers,
    )
    assert loft.status_code == 402
    assert loft.json()["error"]["details"]["operations"] == ["loft"]

    surface = api_client.post(
        f"/api/v1/models/{MISSING}/edits",
        json={"operations": [{"type": "nurbs_surface"}]},
        headers=free_actor.headers,
    )
    assert surface.status_code == 402
    assert surface.json()["error"]["details"]["operations"] == ["nurbs_surface"]

    analytic = api_client.post(
        f"/api/v1/models/{MISSING}/edits",
        json={"operations": [{"type": "analytic_surface_patch"}]},
        headers=free_actor.headers,
    )
    assert analytic.status_code == 402
    assert analytic.json()["error"]["details"]["operations"] == ["analytic_surface_patch"]


def test_free_keeps_basic_export_and_pro_passes_the_tier_gate(
    api_client: TestClient, free_actor: Actor, actor: Actor
) -> None:
    basic = api_client.post(
        f"/api/v1/models/{MISSING}/exports",
        json={"format": "stl"},
        headers=free_actor.headers,
    )
    assert basic.status_code == 404

    paid = api_client.post(
        f"/api/v1/models/{MISSING}/exports",
        json={"format": "step"},
        headers=actor.headers,
    )
    assert paid.status_code == 404
