"""A wizard request becomes a geometry job and a finalized project version."""

import copy
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.geometry.operations import OperationPlan
from app.jobs.kernel_exec import ExecutedPlan, run_plan
from app.models.core import WorkspaceRole
from app.models.execution import Job, JobStatus, Operation
from app.models.versioning import ProjectVersion, VersionState
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401
from tests.integration.test_imports_api import run_all


def test_house_box_creates_a_project_job_and_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом у озера",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "l_shape",
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["job"]["type"] == "build_house_box"
    assert accepted["height_mm"] == 6_000

    project_id = accepted["project_id"]
    before = api_client.get(f"/api/v1/projects/{project_id}", headers=actor.headers).json()
    assert before["name"] == "Дом у озера" and before["head_version"] is None

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["project_id"] == project_id and result["status"] == "executed"
    assert result["floor_plan"]["id"] == f"project-{project_id}-floor-1"
    assert len(result["floor_plan"]["walls"]) == 6

    version = api_client.get(
        f"/api/v1/versions/{result['version_id']}", headers=actor.headers
    ).json()
    assert version["state"] == "finalized"
    assert version["provenance"]["operation"] == "build_house_box"
    assert version["provenance"]["house_box"]["request"]["shape"] == "l_shape"
    floor_plan = api_client.get(f"/api/v1/projects/{project_id}/floor-plan", headers=actor.headers)
    assert floor_plan.status_code == 200, floor_plan.text
    assert floor_plan.json() == result["floor_plan"]
    floor_set = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floor_set.status_code == 200, floor_set.text
    assert [level["elevation_mm"] for level in floor_set.json()["levels"]] == [0, 3_000]
    assert all(len(level["plan"]["walls"]) == 6 for level in floor_set.json()["levels"])
    scene = api_client.get(f"/api/v1/models/{result['version_id']}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert nodes["floor_1"]["parent_id"] == "floor_1_group"
    assert nodes["floor_2"]["parent_id"] == "floor_2_group"
    assert nodes["roof"]["parent_id"] == "roof_group"
    assert not any(node_id.startswith("stair_") for node_id in nodes)
    takeoff_response = api_client.get(
        f"/api/v1/projects/{project_id}/construction-takeoff", headers=actor.headers
    )
    assert takeoff_response.status_code == 200, takeoff_response.text
    takeoff = takeoff_response.json()
    quantities = {line["code"]: line["quantity"] for line in takeoff["quantities"]}
    assert takeoff["version_id"] == result["version_id"]
    assert takeoff["floors"] == 2 and takeoff["floor_height_mm"] == 3_000
    assert quantities == {
        "footprint_area": 72.0,
        "total_floor_area": 144.0,
        "plan_wall_length": 40.0,
        "door_count": 0.0,
        "window_count": 0.0,
        "gross_wall_area": 240.0,
        "net_wall_area": 240.0,
        "gross_wall_volume": 60.0,
    }
    assert takeoff["priced"] is False and takeoff["currency"] is None
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(result["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [op.operation_type for op in logged] == [
        "create_box",
        "create_box",
        "boolean",
        "shell",
        "create_box",
        "create_box",
        "boolean",
        "shell",
        "create_box",
        "create_box",
        "boolean",
    ]


def test_upper_floor_setback_persists_aligned_exact_plans(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "upper_floor_setback_mm": 500,
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["house_box"]["request"]["upper_floor_setback_mm"] == 500

    floor_set = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floor_set.status_code == 200, floor_set.text
    levels = floor_set.json()["levels"]
    assert levels[0]["plan"]["rooms"][0]["outline"][0] == [0, 0]
    assert levels[1]["plan"]["rooms"][0]["outline"] == [
        [500, 500],
        [11_500, 500],
        [11_500, 7_500],
        [500, 7_500],
    ]
    assert levels[2]["plan"]["rooms"][0]["outline"] == levels[1]["plan"]["rooms"][0]["outline"]


def test_per_side_setback_persists_asymmetric_exact_plans(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "rectangle",
            "upper_floor_setback_sides_mm": {"x_max_mm": 3_000, "y_min_mm": 1_000},
            "stair": {"kind": "straight", "placement": "right"},
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    stored = (job.result or {})["house_box"]["request"]
    assert stored["upper_floor_setback_mm"] == 0
    assert stored["upper_floor_setback_sides_mm"] == {
        "x_min_mm": 0,
        "x_max_mm": 3_000,
        "y_min_mm": 1_000,
        "y_max_mm": 0,
    }

    floor_set = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floor_set.status_code == 200, floor_set.text
    levels = floor_set.json()["levels"]
    assert levels[0]["plan"]["rooms"][0]["outline"][2] == [12_000, 8_000]
    assert levels[1]["plan"]["rooms"][0]["outline"] == [
        [0, 1_000],
        [9_000, 1_000],
        [9_000, 8_000],
        [0, 8_000],
    ]
    assert levels[1]["plan"]["stairs"], levels[1]["plan"]


def test_per_side_setback_rejections_create_no_project(
    api_client: TestClient, actor: Actor
) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    cases = [
        (
            {
                **base,
                "upper_floor_setback_mm": 200,
                "upper_floor_setback_sides_mm": {"x_min_mm": 1},
            },
            "not both",
        ),
        ({**base, "upper_floor_setback_sides_mm": {}}, "at least one positive side"),
        ({**base, "upper_floor_setback_sides_mm": {"y_min_mm": 6_500}}, "at least 2000 mm"),
        ({**base, "upper_floor_setback_sides_mm": {"x_min_mm": "100"}}, "x_min_mm"),
        ({**base, "upper_floor_setback_sides_mm": {"front_mm": 100}}, "front_mm"),
        (
            {
                **base,
                "upper_floor_setback_sides_mm": {"y_min_mm": 500},
                "stair": {"kind": "straight", "placement": "left"},
            },
            "does not fit inside the setback upper floor",
        ),
    ]
    for payload, message in cases:
        rejected = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert rejected.status_code == 422, (payload, rejected.text)
        assert message in rejected.text, (payload, rejected.text)
    projects = api_client.get(
        "/api/v1/projects", params={"workspace_id": str(actor.workspace.id)}, headers=actor.headers
    )
    assert projects.json() == []


def test_per_floor_setbacks_persist_stepped_exact_plans(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "upper_floor_setbacks_mm": [
                {"x_max_mm": 1_500},
                {"x_max_mm": 3_000, "y_min_mm": 1_000},
            ],
            "stair": {"kind": "straight", "placement": "right"},
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    stored = (job.result or {})["house_box"]["request"]
    assert stored["upper_floor_setback_mm"] == 0
    assert "upper_floor_setback_sides_mm" not in stored
    assert stored["upper_floor_setbacks_mm"] == [
        {"x_min_mm": 0, "x_max_mm": 1_500, "y_min_mm": 0, "y_max_mm": 0},
        {"x_min_mm": 0, "x_max_mm": 3_000, "y_min_mm": 1_000, "y_max_mm": 0},
    ]

    floor_set = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floor_set.status_code == 200, floor_set.text
    levels = floor_set.json()["levels"]
    assert levels[1]["plan"]["rooms"][0]["outline"] == [
        [0, 0],
        [10_500, 0],
        [10_500, 8_000],
        [0, 8_000],
    ]
    assert levels[2]["plan"]["rooms"][0]["outline"] == [
        [0, 1_000],
        [9_000, 1_000],
        [9_000, 8_000],
        [0, 8_000],
    ]
    assert levels[1]["plan"]["stairs"] and levels[2]["plan"]["stairs"], levels


def test_per_floor_setback_rejections_create_no_project(
    api_client: TestClient, actor: Actor
) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 3,
        "shape": "rectangle",
    }
    levels = [{"x_min_mm": 100}, {"x_min_mm": 200}]
    cases = [
        ({**base, "upper_floor_setback_mm": 200, "upper_floor_setbacks_mm": levels}, "only one"),
        (
            {
                **base,
                "upper_floor_setback_sides_mm": {"x_min_mm": 1},
                "upper_floor_setbacks_mm": levels,
            },
            "only one",
        ),
        ({**base, "upper_floor_setbacks_mm": levels[:1]}, "exactly one entry per upper floor"),
        ({**base, "upper_floor_setbacks_mm": []}, "at least 1 item"),
        ({**base, "upper_floor_setbacks_mm": [{}, {}]}, "at least one positive side"),
        (
            {**base, "upper_floor_setbacks_mm": [{"x_min_mm": 1_000}, {"x_min_mm": 500}]},
            "no overhang",
        ),
        ({**base, "upper_floor_setbacks_mm": [{}, {"y_min_mm": 6_500}]}, "at least 2000 mm"),
        ({**base, "upper_floor_setbacks_mm": [{}, {"x_min_mm": "100"}]}, "x_min_mm"),
        ({**base, "upper_floor_setbacks_mm": [{}, {"x_min_mm": True}]}, "x_min_mm"),
        ({**base, "upper_floor_setbacks_mm": [{}, {"front_mm": 100}]}, "front_mm"),
        (
            {
                **base,
                "upper_floor_setbacks_mm": [{}, {"y_min_mm": 500}],
                "stair": {"kind": "straight", "placement": "left"},
            },
            "does not fit inside the setback upper floor",
        ),
    ]
    for payload, message in cases:
        rejected = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert rejected.status_code == 422, (payload, rejected.text)
        assert message in rejected.text, (payload, rejected.text)
    projects = api_client.get(
        "/api/v1/projects", params={"workspace_id": str(actor.workspace.id)}, headers=actor.headers
    )
    assert projects.json() == []


def test_worker_revalidates_forged_per_floor_setbacks(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "upper_floor_setbacks_mm": [{"x_max_mm": 1_000}, {"x_max_mm": 2_000}],
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    queued = db_session.get(Job, uuid.UUID(response.json()["job"]["job_id"]))
    assert queued is not None
    # A tampered queue entry that bypassed the API: the top floor overhangs floor 2.
    tampered = copy.deepcopy(queued.input)
    tampered["request"]["upper_floor_setbacks_mm"] = [{"x_max_mm": 2_000}, {"x_max_mm": 1_000}]
    queued.input = tampered
    db_session.flush()

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "invalid_house_box"
    assert "no overhang" in str(job.error)


def test_house_box_api_reports_dimension_errors(api_client: TestClient, actor: Actor) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 1_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "length_mm" in response.text


def test_multifloor_stair_creates_aligned_plans_and_floor_scene_groups(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с лестницей",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "rectangle",
            "stair": {
                "width_mm": 1_000,
                "tread_depth_mm": 280,
                "step_count": 17,
                "placement": "center",
                "railing": True,
                "material_id": "interior.wood.oak-natural.v1",
            },
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    version_id = (job.result or {})["version_id"]

    floors_response = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers
    )
    assert floors_response.status_code == 200, floors_response.text
    floors = floors_response.json()
    assert floors["version_id"] == version_id
    assert [level["elevation_mm"] for level in floors["levels"]] == [0, 3_000]
    assert floors["levels"][0]["plan"]["stairs"][0]["role"] == "up"
    assert floors["levels"][1]["plan"]["stairs"][0]["role"] == "down"
    assert (
        floors["levels"][0]["plan"]["stairs"][0]["outline"]
        == floors["levels"][1]["plan"]["stairs"][0]["outline"]
    )

    scene_response = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene_response.status_code == 200, scene_response.text
    nodes = {node["id"]: node for node in scene_response.json()["nodes"]}
    assert nodes["floor_1_group"]["kind"] == "group"
    assert nodes["floor_2_group"]["kind"] == "group"
    assert nodes["roof_group"]["kind"] == "group"
    assert nodes["floor_1"]["parent_id"] == "floor_1_group"
    assert nodes["stair_1_2"]["parent_id"] == "floor_1_group"
    assert nodes["stair_1_2"]["appearance"]["catalog_material_id"] == "interior.wood.oak-natural.v1"

    layout = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={"base_version_id": version_id, "floor_index": 1, "room_count": 3},
        headers=actor.headers,
    )
    assert layout.status_code == 201, layout.text
    laid_out = layout.json()
    assert laid_out["floor_plan"]["stairs"] == floors["levels"][1]["plan"]["stairs"]
    assert len(laid_out["floor_plan"]["rooms"]) == 3
    stair_y = [point[1] for point in laid_out["floor_plan"]["stairs"][0]["outline"]]
    assert all(
        max(point[1] for point in room["outline"]) <= min(stair_y)
        or min(point[1] for point in room["outline"]) >= max(stair_y)
        for room in laid_out["floor_plan"]["rooms"]
    )

    revised_response = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers
    )
    assert revised_response.status_code == 200, revised_response.text
    revised = revised_response.json()
    assert revised["version_id"] == laid_out["version_id"]
    assert revised["levels"][0]["plan"] == floors["levels"][0]["plan"]
    assert revised["levels"][1]["plan"] == laid_out["floor_plan"]

    lower_layout = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={"base_version_id": laid_out["version_id"], "floor_index": 0, "room_count": 3},
        headers=actor.headers,
    )
    assert lower_layout.status_code == 201, lower_layout.text
    all_floors_version_id = lower_layout.json()["version_id"]
    all_floors = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert all_floors.status_code == 200, all_floors.text
    assert all_floors.json()["version_id"] == all_floors_version_id
    assert [len(level["plan"]["rooms"]) for level in all_floors.json()["levels"]] == [3, 3]
    assert [level["plan"]["stairs"][0]["role"] for level in all_floors.json()["levels"]] == [
        "up",
        "down",
    ]

    alignment = api_client.get(
        f"/api/v1/projects/{project_id}/floor-plans/cross-floor-alignment",
        headers=actor.headers,
    )
    assert alignment.status_code == 200, alignment.text
    report = alignment.json()
    assert report["version_id"] == all_floors_version_id
    assert report["structural_engineering"] is False
    assert report["plumbing_stack_engineering"] is False
    assert len(report["pairs"]) == 1
    assert report["pairs"][0]["partitions"]["lower_count"] == 3
    assert report["pairs"][0]["partitions"]["upper_count"] == 3
    assert report["pairs"][0]["partitions"]["aligned_lower_count"] == 3
    assert report["pairs"][0]["wet_zones"]["status"] == "not_typed"
    assert "does not calculate load paths" in report["disclaimer"]

    missing_floor = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={
            "base_version_id": all_floors_version_id,
            "floor_index": 2,
            "room_count": 2,
        },
        headers=actor.headers,
    )
    assert missing_floor.status_code == 422, missing_floor.text
    assert "requested floor does not exist" in missing_floor.text

    elevated_furniture = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={
            "base_version_id": all_floors_version_id,
            "floor_index": 1,
            "room_count": 2,
            "auto_furnish": True,
            "room_requirements": [
                {
                    "kind": "bedroom",
                    "name": "Bedroom",
                    "min_area_m2": 2,
                    "max_area_m2": 200,
                },
                {
                    "kind": "living_room",
                    "name": "Living room",
                    "min_area_m2": 2,
                    "max_area_m2": 200,
                },
            ],
        },
        headers=actor.headers,
    )
    assert elevated_furniture.status_code == 201, elevated_furniture.text
    furnished_layout = elevated_furniture.json()
    assert furnished_layout["furniture_job_id"]
    (furniture_job,) = run_all(db_session, storage)
    assert furniture_job.status is JobStatus.succeeded, furniture_job.error
    assert (furniture_job.result or {})["floor_elevation_mm"] == 3_000
    furnished_scene = api_client.get(
        f"/api/v1/models/{(furniture_job.result or {})['version_id']}/scene",
        headers=actor.headers,
    )
    assert furnished_scene.status_code == 200, furnished_scene.text
    furniture_nodes = [node for node in furnished_scene.json()["nodes"] if node.get("footprint_mm")]
    assert furniture_nodes
    assert all(node["world_transform"][2][3] == 3_000 for node in furniture_nodes)

    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(version_id))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert len(logged) == 44
    assert sum(operation.operation_type == "shell" for operation in logged) == 2


def test_transition_specific_stairs_persist_and_render_distinct_floor_connections(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с разными лестницами",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "stairs": [
                {
                    "kind": "straight",
                    "placement": "left",
                    "railing": False,
                    "material_id": "interior.wood.oak-natural.v1",
                },
                {
                    "kind": "l_turn",
                    "placement": "right",
                    "turn": "right",
                    "railing": False,
                    "material_id": "interior.stone.grey-v1",
                },
            ],
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    stored = result["house_box"]["request"]
    assert stored["stair"] is None
    assert [stair["kind"] for stair in stored["stairs"]] == ["straight", "l_turn"]

    floor_set = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floor_set.status_code == 200, floor_set.text
    levels = floor_set.json()["levels"]
    assert [stair["kind"] for stair in levels[1]["plan"]["stairs"]] == ["straight", "l_turn"]
    assert levels[0]["plan"]["stairs"][0]["outline"] != levels[2]["plan"]["stairs"][0]["outline"]

    scene = api_client.get(f"/api/v1/models/{result['version_id']}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert nodes["stair_1_2"]["name"].startswith("Лестница")
    assert nodes["stair_2_3"]["name"].startswith("Г-образная")
    assert nodes["stair_1_2"]["appearance"]["catalog_material_id"] == "interior.wood.oak-natural.v1"
    assert nodes["stair_2_3"]["appearance"]["catalog_material_id"] == "interior.stone.grey-v1"


def test_stair_rejects_impossible_or_unknown_material_before_enqueue(
    api_client: TestClient, actor: Actor
) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    impossible = api_client.post(
        "/api/v1/house-boxes",
        json={**base, "length_mm": 4_000, "stair": {"step_count": 17}},
        headers=actor.headers,
    )
    assert impossible.status_code == 422
    assert "do not fit" in impossible.text

    forged = api_client.post(
        "/api/v1/house-boxes",
        json={**base, "stair": {"material_id": "interior.wood.forged.v1"}},
        headers=actor.headers,
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["details"]["material_id"] == "interior.wood.forged.v1"


def test_transition_specific_stairs_reject_ambiguous_or_incomplete_requests(
    api_client: TestClient, actor: Actor
) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 3,
        "shape": "rectangle",
    }
    cases = [
        ({**base, "stairs": [{"kind": "straight"}]}, "exactly one entry per floor transition"),
        (
            {
                **base,
                "stair": {"kind": "straight"},
                "stairs": [{"kind": "straight"}, {"kind": "straight"}],
            },
            "either stair or stairs",
        ),
        (
            {
                **base,
                "stairs": [
                    {"kind": "straight"},
                    {"kind": "straight", "material_id": "interior.wood.forged.v1"},
                ],
            },
            "unknown interior material",
        ),
    ]
    for payload, message in cases:
        response = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert response.status_code == 422, response.text
        assert message in response.text


def test_worker_revalidates_tampered_transition_stair_count(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "stairs": [{"kind": "straight"}, {"kind": "straight"}],
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    queued = db_session.get(Job, uuid.UUID(response.json()["job"]["job_id"]))
    assert queued is not None
    tampered = copy.deepcopy(queued.input)
    tampered["request"]["stairs"] = tampered["request"]["stairs"][:1]
    queued.input = tampered
    db_session.flush()

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "invalid_house_box"
    assert "exactly one entry per floor transition" in str(job.error)


def test_l_turn_stair_creates_l_plans_scene_groups_and_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с Г-лестницей",
            "length_mm": 12_000,
            "width_mm": 9_000,
            "floor_height_mm": 3_000,
            "floors": 3,
            "shape": "rectangle",
            "stair": {
                "kind": "l_turn",
                "width_mm": 1_000,
                "tread_depth_mm": 280,
                "lower_step_count": 9,
                "upper_step_count": 7,
                "turn": "left",
                "placement": "left",
                "railing": True,
                "material_id": "interior.wood.oak-natural.v1",
            },
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    assert response.json()["height_mm"] == 9_000

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    version_id = result["version_id"]
    assert result["house_box"]["request"]["stair"]["kind"] == "l_turn"

    floors = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floors.status_code == 200, floors.text
    levels = floors.json()["levels"]
    assert [level["elevation_mm"] for level in levels] == [0, 3_000, 6_000]
    assert [[stair["role"] for stair in level["plan"]["stairs"]] for level in levels] == [
        ["up"],
        ["down", "up"],
        ["down"],
    ]
    up = levels[0]["plan"]["stairs"][0]
    assert up["kind"] == "l_turn" and up["turn"] == "left"
    assert len(up["outline"]) == 6 and len(up["landing"]) == 4
    assert [flight["direction"] for flight in up["flights"]] == ["+x", "+y"]
    assert up["step_count"] == 17
    assert levels[2]["plan"]["stairs"][0]["outline"] == up["outline"]

    scene = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert {"floor_1_group", "floor_2_group", "floor_3_group", "roof_group"} <= set(nodes)
    assert nodes["stair_1_2"]["parent_id"] == "floor_1_group"
    assert nodes["stair_2_3"]["parent_id"] == "floor_2_group"
    assert nodes["stair_1_2"]["name"].startswith("Г-образная лестница")
    for rail in ("lower_inner", "lower_outer", "landing_side", "landing_back", "upper_inner"):
        assert nodes[f"rail_{rail}_2_3"]["parent_id"] == "floor_2_group"
        assert (
            nodes[f"rail_{rail}_1_2"]["appearance"]["catalog_material_id"]
            == "interior.wood.oak-natural.v1"
        )

    layout = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={"base_version_id": version_id, "floor_index": 1, "room_count": 2},
        headers=actor.headers,
    )
    assert layout.status_code == 201, layout.text
    laid_out = layout.json()["floor_plan"]
    assert laid_out["stairs"] == levels[1]["plan"]["stairs"]
    stair_y = [point[1] for point in up["outline"]]
    assert all(
        max(point[1] for point in room["outline"]) <= min(stair_y)
        or min(point[1] for point in room["outline"]) >= max(stair_y)
        for room in laid_out["rooms"]
    )

    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(version_id))
        .order_by(Operation.sequence_no)
        .all()
    )
    # 3 shells, 2 x 2 L openings, roof, 2 x (17 bodies + 16 fuses + 10 rail operations)
    assert len(logged) == 6 + 8 + 1 + 2 * 43
    assert sum(op.operation_type == "rotate" for op in logged) == 8


def test_l_turn_stair_fails_closed_before_enqueue(api_client: TestClient, actor: Actor) -> None:
    base = {
        "workspace_id": str(actor.workspace.id),
        "length_mm": 12_000,
        "width_mm": 8_000,
        "floor_height_mm": 3_000,
        "floors": 2,
        "shape": "rectangle",
    }
    l_stair = {"kind": "l_turn", "lower_step_count": 8, "upper_step_count": 8}
    u_stair = {"kind": "u_turn", "flight_step_count": 8}
    cases = [
        ({**base, "width_mm": 3_500, "stair": l_stair}, "do not fit"),
        ({**base, "floor_height_mm": 6_000, "stair": l_stair}, "120-220 mm rise"),
        ({**base, "stair": {**l_stair, "tread_depth_mm": 400}}, "550-700 mm"),
        ({**base, "stair": {**l_stair, "width_mm": 650}}, "width_mm"),
        ({**base, "stair": {**l_stair, "step_count": 17}}, "step_count"),
        ({**base, "stair": {"kind": "helical"}}, "helical"),
        ({**base, "floors": 1, "stair": l_stair}, "at least two floors"),
        ({**base, "stair": {**l_stair, "material_id": "interior.wood.forged.v1"}}, "forged"),
        ({**base, "width_mm": 2_600, "stair": u_stair}, "do not fit"),
        ({**base, "stair": {**u_stair, "flight_step_count": 4}}, "flight_step_count"),
        ({**base, "stair": {**u_stair, "step_count": 17}}, "step_count"),
        ({**base, "floors": 1, "upper_floor_setback_mm": 200}, "at least two floors"),
        ({**base, "shape": "l_shape", "upper_floor_setback_mm": 200}, "rectangular house"),
        (
            {
                **base,
                "upper_floor_setback_mm": 1_500,
                "stair": {"kind": "straight", "placement": "left"},
            },
            "does not fit inside the setback upper floor",
        ),
    ]
    for payload, message in cases:
        rejected = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert rejected.status_code == 422, (payload, rejected.text)
        assert message in rejected.text, (payload, rejected.text)
    projects = api_client.get(
        "/api/v1/projects", params={"workspace_id": str(actor.workspace.id)}, headers=actor.headers
    )
    assert projects.status_code == 200, projects.text
    assert projects.json() == []


def test_u_turn_stair_creates_parallel_plan_scene_and_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    response = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Дом с П-лестницей",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 2,
            "shape": "rectangle",
            "stair": {
                "kind": "u_turn",
                "width_mm": 1_000,
                "tread_depth_mm": 280,
                "flight_step_count": 8,
                "turn": "right",
                "placement": "center",
                "railing": True,
                "material_id": "interior.wood.oak-natural.v1",
            },
        },
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    version_id = result["version_id"]
    assert result["house_box"]["request"]["stair"]["kind"] == "u_turn"

    floors = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floors.status_code == 200, floors.text
    up = floors.json()["levels"][0]["plan"]["stairs"][0]
    assert up["kind"] == "u_turn" and up["turn"] == "right"
    assert len(up["outline"]) == 4 and len(up["landing"]) == 4
    assert [flight["direction"] for flight in up["flights"]] == ["+x", "-x"]
    assert [flight["step_count"] for flight in up["flights"]] == [8, 8]

    scene = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert nodes["stair_1_2"]["name"].startswith("П-образная лестница")
    for rail in ("lower_inner", "landing_left", "landing_back", "landing_right", "upper_outer"):
        node = nodes[f"rail_{rail}_1_2"]
        assert node["parent_id"] == "floor_1_group"
        assert node["appearance"]["catalog_material_id"] == "interior.wood.oak-natural.v1"

    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(version_id))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert len(logged) == 51
    assert sum(op.operation_type == "rotate" for op in logged) == 4


WINDER_HOUSE = {
    "label": "Дом с забежной лестницей",
    "length_mm": 12_000,
    "width_mm": 9_000,
    "floor_height_mm": 3_000,
    "floors": 3,
    "shape": "rectangle",
}
WINDER_STAIR = {
    "kind": "winder_turn",
    "width_mm": 1_000,
    "tread_depth_mm": 280,
    "lower_step_count": 6,
    "upper_step_count": 8,
    "newel_mm": 250,
    "turn": "right",
    "placement": "left",
    "railing": False,
    "material_id": "interior.wood.oak-natural.v1",
}


def test_winder_stair_creates_aligned_plans_scene_and_immutable_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    body = {"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": WINDER_STAIR}
    headers = {**actor.headers, "Idempotency-Key": f"winder-{uuid.uuid4()}"}
    response = api_client.post("/api/v1/house-boxes", json=body, headers=headers)
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    assert response.json()["height_mm"] == 9_000
    repeated = api_client.post("/api/v1/house-boxes", json=body, headers=headers)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["job"]["job_id"] == response.json()["job"]["job_id"]

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    version_id = result["version_id"]
    assert result["house_box"]["request"]["stair"] == WINDER_STAIR
    bodies = {item["name"]: item for item in result["bodies"]}
    for name in ("stair_1_2_step_1", "stair_2_3_step_1"):
        assert bodies[name]["solids"] == 1 and bodies[name]["valid"]

    floors = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floors.status_code == 200, floors.text
    levels = floors.json()["levels"]
    assert [[stair["role"] for stair in level["plan"]["stairs"]] for level in levels] == [
        ["up"],
        ["down", "up"],
        ["down"],
    ]
    up = levels[0]["plan"]["stairs"][0]
    assert up["kind"] == "winder_turn" and up["turn"] == "right" and up["railing"] is False
    assert len(up["outline"]) == 6 and up["landing"] is None
    assert [len(winder) for winder in up["winders"]] == [4, 6, 4] and len(up["newel"]) == 4
    assert [flight["direction"] for flight in up["flights"]] == ["+x", "-y"]
    assert [flight["step_count"] for flight in up["flights"]] == [6, 8]
    assert levels[2]["plan"]["stairs"][0]["outline"] == up["outline"]

    scene = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    stair_nodes = [name for name in nodes if name.startswith(("stair_", "rail_"))]
    assert stair_nodes == ["stair_1_2", "stair_2_3"]
    assert nodes["stair_1_2"]["name"] == "Лестница с забежными ступенями 1 → 2"
    assert nodes["stair_2_3"]["parent_id"] == "floor_2_group"
    assert nodes["stair_1_2"]["appearance"]["catalog_material_id"] == "interior.wood.oak-natural.v1"

    def operation_log() -> list[tuple[str, dict[str, object]]]:
        return [
            (operation.operation_type, operation.params)
            for operation in db_session.query(Operation)
            .filter(Operation.project_version_id == uuid.UUID(version_id))
            .order_by(Operation.sequence_no)
        ]

    logged = operation_log()
    # 3 shells, 2 x 2 L openings, roof, 2 x (17 bodies + 16 fuses); no rails.
    assert len(logged) == 6 + 8 + 1 + 2 * 33
    assert [params["id"] for kind, params in logged if kind == "extrude"] == [
        f"stair_{flight}_winder_{index}" for flight in ("1_2", "2_3") for index in (1, 2, 3)
    ]
    assert not any(kind == "rotate" for kind, _ in logged)

    # A later layout is a child version: the winder root version itself never changes.
    root = db_session.get(ProjectVersion, uuid.UUID(version_id))
    assert root is not None and root.state is VersionState.finalized
    provenance = copy.deepcopy(root.provenance)
    layout = api_client.post(
        f"/api/v1/projects/{project_id}/floor-plan/auto-layout",
        json={"base_version_id": version_id, "floor_index": 1, "room_count": 2},
        headers=actor.headers,
    )
    assert layout.status_code == 201, layout.text
    laid_out = layout.json()
    assert laid_out["version_id"] != version_id
    assert laid_out["floor_plan"]["stairs"] == levels[1]["plan"]["stairs"]
    stair_y = [point[1] for point in up["outline"]]
    assert all(
        max(point[1] for point in room["outline"]) <= min(stair_y)
        or min(point[1] for point in room["outline"]) >= max(stair_y)
        for room in laid_out["floor_plan"]["rooms"]
    )
    db_session.expire_all()
    assert root.provenance == provenance and operation_log() == logged
    with pytest.raises(DBAPIError, match="immutable|finalized"), db_session.begin_nested():
        db_session.execute(
            sa.update(ProjectVersion)
            .where(ProjectVersion.id == root.id)
            .values(provenance={"forged": True})
        )


def test_winder_stair_creation_requires_a_workspace_editor(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    body = {"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": WINDER_STAIR}
    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    stranger = make_actor(db_session)
    assert api_client.post("/api/v1/house-boxes", json=body).status_code == 401
    for outsider, statuses in ((viewer, {403}), (stranger, {403, 404})):
        denied = api_client.post("/api/v1/house-boxes", json=body, headers=outsider.headers)
        assert denied.status_code in statuses, denied.text
    assert db_session.query(Job).filter(Job.workspace_id == actor.workspace.id).count() == 0

    accepted = api_client.post("/api/v1/house-boxes", json=body, headers=actor.headers)
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    hidden = api_client.get(
        f"/api/v1/projects/{accepted.json()['project_id']}/floor-plans", headers=stranger.headers
    )
    assert hidden.status_code == 404


def test_winder_stair_fails_closed_before_enqueue(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    base = {"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "floors": 2}
    cases: list[tuple[dict[str, object], dict[str, object], str]] = [
        ({"width_mm": 3_500}, {}, "do not fit"),
        ({"floor_height_mm": 6_000}, {}, "120-220 mm rise"),
        ({}, {"tread_depth_mm": 400}, "550-700 mm"),
        ({}, {"newel_mm": 500}, "walking-line"),
        ({}, {"newel_mm": 199}, "newel_mm"),
        ({}, {"width_mm": "1000"}, "width_mm"),
        ({}, {"lower_step_count": 2}, "lower_step_count"),
        ({}, {"lower_step_count": 14, "upper_step_count": 14}, "10-30 risers"),
        ({}, {"step_count": 17}, "step_count"),
        ({}, {"flight_step_count": 8}, "flight_step_count"),
        ({}, {"railing": True}, "railing"),
        ({}, {"turn": "up"}, "turn"),
        ({}, {"material_id": "interior.wood.forged.v1"}, "forged"),
        ({"floors": 1}, {}, "at least two floors"),
        ({"shape": "l_shape"}, {}, "rectangular house"),
        ({"upper_floor_setback_mm": 500}, {}, "setback upper floor"),
    ]
    for house, stair, message in cases:
        payload = {**base, **house, "stair": {**WINDER_STAIR, **stair}}
        rejected = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert rejected.status_code == 422, (payload, rejected.text)
        assert message in rejected.text, (payload, rejected.text)
    assert db_session.query(Job).filter(Job.workspace_id == actor.workspace.id).count() == 0


def test_winder_worker_revalidates_a_tampered_job_request(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": WINDER_STAIR},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    queued = db_session.get(Job, uuid.UUID(accepted.json()["job"]["job_id"]))
    assert queued is not None
    tampered = copy.deepcopy(queued.input)
    tampered["request"]["stair"]["railing"] = True
    queued.input = tampered
    db_session.flush()
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "invalid_house_box"


def test_winder_job_rejects_a_disconnected_kernel_flight(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": WINDER_STAIR},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text

    def split_flight(plan: OperationPlan) -> ExecutedPlan:
        executed = run_plan(plan)
        for body in executed.bodies:
            if body["name"] == "stair_2_3_step_1":
                body["solids"] = 2
        return executed

    monkeypatch.setattr("app.jobs.house_box.run_plan", split_flight)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "kernel_bad_output"
    assert (
        db_session.query(ProjectVersion)
        .filter(ProjectVersion.project_id == uuid.UUID(accepted.json()["project_id"]))
        .count()
        == 0
    )


def test_rectangular_house_auto_layout_creates_an_immutable_plan_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "Планируемый дом",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()
    (job,) = run_all(db_session, storage)
    base_version_id = str((job.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 3},
        headers=actor.headers,
    )

    assert response.status_code == 201, response.text
    layout = response.json()
    assert layout["sequence_no"] == 2 and layout["version_id"] != base_version_id
    assert len(layout["floor_plan"]["rooms"]) == 3
    assert len(layout["floor_plan"]["walls"]) == 6
    assert [opening["wall"] for opening in layout["floor_plan"]["openings"]] == [4, 5]
    current = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan", headers=actor.headers
    )
    assert current.json() == layout["floor_plan"]
    takeoff = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=actor.headers,
    ).json()
    quantities = {line["code"]: line["quantity"] for line in takeoff["quantities"]}
    assert quantities["door_count"] == 2
    assert quantities["plan_wall_length"] == 56
    assert quantities["total_floor_area"] == 96
    operations = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(layout["version_id"]))
        .order_by(Operation.sequence_no)
        .all()
    )
    assert operations[-1].operation_type == "update_floor_plan"

    revised = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": layout["version_id"], "room_count": 2},
        headers=actor.headers,
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["sequence_no"] == 3
    assert len(revised.json()["floor_plan"]["rooms"]) == 2

    stale = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 2},
        headers=actor.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"


def test_l_house_auto_layout_records_decomposition_provenance(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "label": "L house",
            "length_mm": 12_000,
            "width_mm": 8_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "l_shape",
        },
        headers=actor.headers,
    ).json()
    (job,) = run_all(db_session, storage)
    base_version_id = str((job.result or {})["version_id"])

    response = api_client.post(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan/auto-layout",
        json={"base_version_id": base_version_id, "room_count": 5},
        headers=actor.headers,
    )

    assert response.status_code == 201, response.text
    layout = response.json()
    assert len(layout["floor_plan"]["rooms"]) == 5
    assert len(layout["floor_plan"]["walls"]) == 11
    assert [opening["wall"] for opening in layout["floor_plan"]["openings"]] == [7, 8, 9, 10]
    assert layout["floor_plan"]["openings"][-1]["offset_mm"] == 3_260
    version = api_client.get(
        f"/api/v1/versions/{layout['version_id']}", headers=actor.headers
    ).json()
    provenance = version["provenance"]["floor_plan_layout"]
    assert provenance["kind"] == "lt_decomposition_v1"
    assert provenance["zone_room_counts"] == [2, 3]
    assert provenance["seam"] == {"a": [6_000.0, 4_000.0], "b": [0.0, 4_000.0]}


def test_floor_plan_is_not_claimed_before_the_house_version_exists(
    api_client: TestClient, actor: Actor
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 8_000,
            "width_mm": 6_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()

    response = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/floor-plan", headers=actor.headers
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    takeoff = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=actor.headers,
    )
    assert takeoff.status_code == 404
    assert takeoff.json()["error"]["code"] == "not_found"


def test_construction_takeoff_hides_foreign_projects(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={
            "workspace_id": str(actor.workspace.id),
            "length_mm": 8_000,
            "width_mm": 6_000,
            "floor_height_mm": 3_000,
            "floors": 1,
            "shape": "rectangle",
        },
        headers=actor.headers,
    ).json()
    run_all(db_session, storage)
    stranger = make_actor(db_session)

    response = api_client.get(
        f"/api/v1/projects/{accepted['project_id']}/construction-takeoff",
        headers=stranger.headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


SPIRAL_STAIR = {
    "kind": "spiral",
    "diameter_mm": 2_200.0,
    "post_diameter_mm": 200.0,
    "step_count": 15,
    "sweep_deg": 300.0,
    "turn": "right",
    "placement": "center",
    "railing": False,
    "material_id": None,
}


def test_spiral_stair_creates_aligned_plans_scene_and_operations(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    body = {"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": SPIRAL_STAIR}
    headers = {**actor.headers, "Idempotency-Key": f"spiral-{uuid.uuid4()}"}
    response = api_client.post("/api/v1/house-boxes", json=body, headers=headers)
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    version_id = result["version_id"]
    assert result["house_box"]["request"]["stair"] == SPIRAL_STAIR
    bodies = {item["name"]: item for item in result["bodies"]}
    for name in ("stair_1_2_step_1", "stair_2_3_step_1"):
        assert bodies[name]["solids"] == 1 and bodies[name]["valid"]

    floors = api_client.get(f"/api/v1/projects/{project_id}/floor-plans", headers=actor.headers)
    assert floors.status_code == 200, floors.text
    levels = floors.json()["levels"]
    up = levels[0]["plan"]["stairs"][0]
    assert up["kind"] == "spiral" and up["turn"] == "right" and up["railing"] is False
    assert len(up["outline"]) == 24 and up["flights"] == [] and up["landing"] is None
    assert up["spiral"]["radius_mm"] == 1_100 and up["spiral"]["sweep_deg"] == 300
    assert levels[2]["plan"]["stairs"][0]["outline"] == up["outline"]

    scene = api_client.get(f"/api/v1/models/{version_id}/scene", headers=actor.headers)
    assert scene.status_code == 200, scene.text
    nodes = {node["id"]: node for node in scene.json()["nodes"]}
    assert nodes["stair_1_2"]["name"] == "Винтовая лестница 1 → 2"
    logged = [
        (operation.operation_type, operation.params)
        for operation in db_session.query(Operation)
        .filter(Operation.project_version_id == uuid.UUID(version_id))
        .order_by(Operation.sequence_no)
    ]
    # 3 shells, 2 sector openings (body + cut), roof, 2 x (15 treads + post + 15 fuses).
    assert len(logged) == 6 + 4 + 1 + 2 * 31


def test_spiral_stair_fails_closed_before_enqueue(
    api_client: TestClient, actor: Actor, db_session: Session
) -> None:
    base = {"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "floors": 2}
    cases: list[tuple[dict[str, object], dict[str, object], str]] = [
        ({"width_mm": 2_800}, {}, "do not fit"),
        ({"floor_height_mm": 6_000}, {}, "120-220 mm rise"),
        ({}, {"sweep_deg": 180.0}, "walking line"),
        ({}, {"diameter_mm": 1_500.0}, "clear tread width"),
        ({}, {"diameter_mm": "2200"}, "diameter_mm"),
        ({}, {"step_count": 15.5}, "step_count"),
        ({}, {"step_count": 21}, "less than or equal to 20"),
        ({}, {"railing": True}, "railing"),
        ({}, {"tread_depth_mm": 280}, "tread_depth_mm"),
        ({"floors": 1}, {}, "at least two floors"),
        ({"shape": "l_shape"}, {}, "rectangular house"),
    ]
    for house, stair, message in cases:
        payload = {**base, **house, "stair": {**SPIRAL_STAIR, **stair}}
        rejected = api_client.post("/api/v1/house-boxes", json=payload, headers=actor.headers)
        assert rejected.status_code == 422, (payload, rejected.text)
        assert message in rejected.text, (payload, rejected.text)
    assert db_session.query(Job).filter(Job.workspace_id == actor.workspace.id).count() == 0


def test_spiral_worker_revalidates_a_tampered_job_request(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": SPIRAL_STAIR},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    queued = db_session.get(Job, uuid.UUID(accepted.json()["job"]["job_id"]))
    assert queued is not None
    tampered = copy.deepcopy(queued.input)
    tampered["request"]["stair"]["railing"] = True
    queued.input = tampered
    db_session.flush()
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "invalid_house_box"


def test_spiral_job_rejects_a_disconnected_kernel_flight(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = api_client.post(
        "/api/v1/house-boxes",
        json={"workspace_id": str(actor.workspace.id), **WINDER_HOUSE, "stair": SPIRAL_STAIR},
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text

    def split_flight(plan: OperationPlan) -> ExecutedPlan:
        executed = run_plan(plan)
        for body in executed.bodies:
            if body["name"] == "stair_2_3_step_1":
                body["solids"] = 2
        return executed

    monkeypatch.setattr("app.jobs.house_box.run_plan", split_flight)
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.failed
    assert (job.error or {})["code"] == "kernel_bad_output"
    assert (
        db_session.query(ProjectVersion)
        .filter(ProjectVersion.project_id == uuid.UUID(accepted.json()["project_id"]))
        .count()
        == 0
    )
