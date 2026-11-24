"""A wizard request becomes a geometry job and a finalized project version."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus, Operation
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
        ({**base, "stair": {"kind": "spiral"}}, "spiral"),
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
