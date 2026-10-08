"""T-055/T-038: the numeric inspector edits a version through the same kernel path as AI."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from worker import geometry as kernel

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models import Operation, ProjectVersion
from app.models.execution import JobStatus
from app.services import edits as edit_service
from app.storage import S3Storage
from tests.integration.conftest import Actor
from tests.integration.test_ai_commands import (  # reuse the fake kernel + helpers
    cleanup_keys,  # noqa: F401
    command,
    kernel_or_fake,  # noqa: F401
    new_project,
    run_all,
)
from tests.integration.test_imports_api import project  # noqa: F401
from tests.integration.test_painting_api import imported_version


def build_box(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> tuple[str, str]:
    """Returns (project_id, version_id) for a plain box built by the stub planner."""
    project_id = new_project(api_client, actor)
    response = command(api_client, actor, project_id, "Box 40x20x8 mm")
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return project_id, str((job.result or {})["version_id"])


def edit(
    api_client: TestClient,
    actor: Actor,
    version_id: str,
    *,
    operations: list[dict[str, Any]],
    **b: Any,
) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/edits",
        json={"operations": operations, **b},
        headers=actor.headers,
    )


def body_name(db_session: Session, version_id: str) -> str:
    version = db_session.get(ProjectVersion, version_id)
    assert version is not None
    bodies = (version.provenance or {})["bodies"]
    return str(bodies[-1]["name"])


def stack(api_client: TestClient, actor: Actor, version_id: str) -> Any:
    return api_client.get(f"/api/v1/models/{version_id}/operation-stack", headers=actor.headers)


def edit_stack(
    api_client: TestClient,
    actor: Actor,
    version_id: str,
    operations: list[dict[str, Any]],
) -> Any:
    return api_client.post(
        f"/api/v1/models/{version_id}/operation-stack",
        json={"operations": operations, "label": "Rebuild feature stack"},
        headers=actor.headers,
    )


def test_dimension_edit_creates_a_child_version_with_the_full_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    target = body_name(db_session, version_id)

    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": target, "width_mm": 60, "height_mm": 12}],
        label="Resize to 60 × 20 × 12 mm",
    )
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "manual_edit"

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    assert result["source_version_id"] == version_id

    child = db_session.get(ProjectVersion, result["version_id"])
    assert child is not None
    assert str(child.parent_version_id) == version_id
    assert child.label == "Resize to 60 × 20 × 12 mm"
    assert child.provenance["operation"] == "manual_edit"

    # The child owns the replayed history plus the edit — the next edit can build on it.
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [op.operation_type for op in logged] == ["create_box", "set_dimensions"]
    assert logged[-1].params["width_mm"] == 60
    assert logged[-1].entity_refs == [target]

    if kernel.available():  # the real kernel actually rescales the body
        size = result["bodies"][-1]["bbox_mm"]["size"]
        assert (round(size[0]), round(size[2])) == (60, 12)


def test_selected_mesh_profile_starts_a_fresh_exact_feature_tree(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    mesh_version_id = imported_version(api_client, actor, db_session, storage, project)
    sketch = {
        "kind": "sketch",
        "points_mm": [[0, 0], [30, 0], [30, 20], [0, 20]],
        "segments": [{"kind": "line"}] * 4,
        "constraints": [],
        "tolerance_mm": 1e-5,
    }
    selected_loft = {
        "id": "selected_loft",
        "type": "loft",
        "sections": [
            {
                "profile": sketch,
                "origin_mm": [0, 0, 10],
                "normal": [0, 0, 1],
                "x_direction": [1, 0, 0],
            },
            {
                "profile": sketch,
                "origin_mm": [0, 0, 20],
                "normal": [0, 0, 1],
                "x_direction": [1, 0, 0],
            },
        ],
    }
    plan = edit_service.build_replacement_plan(
        operations=[selected_loft], label="Exact CAD from selected mesh profile"
    )
    assert plan.expected_outputs == ["selected_loft"]
    assert plan.operations[0].model_dump(mode="json")["sections"][0]["profile"] == sketch

    # The host fallback only executes primitive creators; the production test image has OCCT
    # and therefore runs the exact sketch/loft operation end to end.
    execution_operation = (
        selected_loft
        if kernel.available()
        else {
            "id": "selected_body",
            "type": "create_box",
            "width_mm": 30,
            "depth_mm": 20,
            "height_mm": 10,
            "origin_mm": [0, 0, 10],
        }
    )
    response = edit(
        api_client,
        actor,
        mesh_version_id,
        replace_history=True,
        label="Exact CAD from selected mesh profile",
        operations=[execution_operation],
    )
    assert response.status_code == 202, response.text

    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    child = db_session.get(ProjectVersion, result["version_id"])
    assert child is not None
    assert str(child.parent_version_id) == mesh_version_id
    assert child.provenance["replaced_history"] is True
    expected_id = "selected_loft" if kernel.available() else "selected_body"
    assert result["plan"]["expected_outputs"] == [expected_id]
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [row.operation_type for row in logged] == [
        "loft" if kernel.available() else "create_box"
    ]
    if kernel.available():
        assert logged[0].params["sections"][0]["profile"]["points_mm"] == [
            [0.0, 0.0],
            [30.0, 0.0],
            [30.0, 20.0],
            [0.0, 20.0],
        ]
    assert (
        db_session.query(Operation).filter(Operation.project_version_id == mesh_version_id).count()
        == 0
    )


def test_operation_stack_reorders_safely_and_preserves_disabled_features(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    target = body_name(db_session, version_id)
    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"id": "move", "type": "translate", "target": target, "offset_mm": [3, 0, 0]}],
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    moved_id = str((job.result or {})["version_id"])

    response = stack(api_client, actor, moved_id)
    assert response.status_code == 200, response.text
    rows = response.json()["operations"]
    assert [(row["id"], row["enabled"], row["dependencies"]) for row in rows] == [
        (target, True, []),
        ("move", True, [target]),
    ]

    # Moving a dependent feature before its body is rejected before a job exists.
    response = edit_stack(
        api_client,
        actor,
        moved_id,
        [{"id": "move", "enabled": True}, {"id": target, "enabled": True}],
    )
    assert response.status_code == 422
    assert "valid plan" in response.json()["error"]["message"]
    assert run_all(db_session, storage) == []

    # Turning off the terminal modifier rebuilds the body but retains the feature row.
    response = edit_stack(
        api_client,
        actor,
        moved_id,
        [{"id": target, "enabled": True}, {"id": "move", "enabled": False}],
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    rebuilt_id = str((job.result or {})["version_id"])
    assert (job.result or {})["plan"]["operations"][-1]["id"] == target
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == rebuilt_id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [(row.params["id"], row.enabled) for row in logged] == [
        (target, True),
        ("move", False),
    ]

    # A normal later edit keeps the disabled feature instead of dropping its JSON.
    response = edit(
        api_client,
        actor,
        rebuilt_id,
        operations=[{"id": "resize", "type": "set_dimensions", "target": target, "height_mm": 9}],
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    final_id = str((job.result or {})["version_id"])
    rows = stack(api_client, actor, final_id).json()["operations"]
    assert [(row["id"], row["enabled"]) for row in rows] == [
        (target, True),
        ("move", False),
        ("resize", True),
    ]

    # Independent modifiers may be reordered, and the disabled one can be restored later.
    response = edit_stack(
        api_client,
        actor,
        final_id,
        [
            {"id": target, "enabled": True},
            {"id": "resize", "enabled": True},
            {"id": "move", "enabled": True},
        ],
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    reordered_id = str((job.result or {})["version_id"])
    rows = stack(api_client, actor, reordered_id).json()["operations"]
    assert [(row["id"], row["enabled"]) for row in rows] == [
        (target, True),
        ("resize", True),
        ("move", True),
    ]


def test_operation_stack_requires_workspace_membership(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    from tests.integration.conftest import make_actor

    _, version_id = build_box(api_client, actor, db_session, storage)
    stranger = make_actor(db_session)
    assert stack(api_client, stranger, version_id).status_code == 404
    response = edit_stack(api_client, stranger, version_id, [{"id": "body", "enabled": True}])
    assert response.status_code == 404


def test_edit_naming_an_unknown_body_is_rejected_before_the_job(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": "nope", "width_mm": 10}],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert run_all(db_session, storage) == []


def test_replacement_cannot_reference_a_body_from_the_discarded_history(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    response = edit(
        api_client,
        actor,
        version_id,
        replace_history=True,
        operations=[{"type": "translate", "target": "source_mesh", "offset_mm": [1, 0, 0]}],
    )
    assert response.status_code == 422
    assert "do not produce an exact body" in response.json()["error"]["message"]
    assert run_all(db_session, storage) == []


def test_replacement_is_rejected_for_an_existing_parametric_feature_tree(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    response = edit(
        api_client,
        actor,
        version_id,
        replace_history=True,
        operations=[
            {
                "type": "create_box",
                "width_mm": 5,
                "depth_mm": 5,
                "height_mm": 5,
            }
        ],
    )
    assert response.status_code == 422
    assert "only available for imported or scanned" in response.json()["error"]["message"]
    assert run_all(db_session, storage) == []


def test_constrained_loft_reaches_the_manual_edit_job_and_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    target = body_name(db_session, version_id)
    sketch = {
        "kind": "sketch",
        "points_mm": [[0, 0], [10, 0.2], [10, 5], [0, 5]],
        "segments": [
            {"kind": "line"},
            {
                "kind": "nurbs",
                "control_points_mm": [[12, 2.5]],
                "degree": 2,
                "weights": [1, 0.8, 1],
                "knots": [0, 1],
                "multiplicities": [3, 3],
            },
            {"kind": "line"},
            {"kind": "line"},
        ],
        "constraints": [
            {"kind": "fixed", "point": 0},
            {"kind": "horizontal", "start": 0, "end": 1},
            {"kind": "distance", "start": 0, "end": 1, "distance_mm": 10},
        ],
    }
    response = edit(
        api_client,
        actor,
        version_id,
        operations=[
            {
                "id": "loft_feature",
                "type": "loft",
                "sections": [
                    {
                        "profile": sketch,
                        "origin_mm": [0, 0, 0],
                        "normal": [0, 1, 1],
                        "x_direction": [1, 0, 0],
                    },
                    {
                        "profile": sketch,
                        "origin_mm": [0, 7.071067811865475, 7.071067811865475],
                        "normal": [0, 1, 1],
                        "x_direction": [1, 0, 0],
                    },
                ],
            },
            {
                "id": "join_loft",
                "type": "boolean",
                "op": "fuse",
                "target": target,
                "tool": "loft_feature",
            },
        ],
        label="Constrained loft",
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    child = db_session.get(ProjectVersion, (job.result or {})["version_id"])
    assert child is not None
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [item.operation_type for item in logged][-2:] == ["loft", "boolean"]
    assert logged[-2].params["sections"][0]["profile"]["constraints"][1]["kind"] == "horizontal"
    assert logged[-2].params["sections"][0]["profile"]["segments"][1]["kind"] == "nurbs"
    assert logged[-2].params["sections"][0]["profile"]["segments"][1]["weights"] == [
        1.0,
        0.8,
        1.0,
    ]
    assert logged[-2].params["sections"][0]["normal"] == [0.0, 1.0, 1.0]
    assert logged[-2].params["sections"][0]["x_direction"] == [1.0, 0.0, 0.0]


def test_nurbs_surface_reaches_the_manual_edit_job_and_operation_log(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    _, version_id = build_box(api_client, actor, db_session, storage)
    response = edit(
        api_client,
        actor,
        version_id,
        operations=[
            {
                "id": "curved_skin",
                "type": "nurbs_surface",
                "control_points_mm": [
                    [[10, 0, 0], [10, 0, 20]],
                    [[10, 10, 0], [10, 10, 20]],
                    [[0, 10, 0], [0, 10, 20]],
                ],
                "weights": [[1, 1], [2**-0.5, 2**-0.5], [1, 1]],
                "u_degree": 2,
                "v_degree": 1,
                "u_knots": [0, 1],
                "v_knots": [0, 1],
                "u_multiplicities": [3, 3],
                "v_multiplicities": [2, 2],
                "thickness_mm": 2,
            }
        ],
        label="Exact NURBS surface",
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    child = db_session.get(ProjectVersion, (job.result or {})["version_id"])
    assert child is not None
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert logged[-1].operation_type == "nurbs_surface"
    assert logged[-1].params["u_degree"] == 2
    assert logged[-1].params["weights"][1][0] == 2**-0.5


def test_analytic_patch_replace_history_creates_an_immutable_child(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    kernel_or_fake: None,  # noqa: F811
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    version_id = imported_version(api_client, actor, db_session, storage, project)
    parent_rows = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == version_id)
        .count()
    )
    response = edit(
        api_client,
        actor,
        version_id,
        replace_history=True,
        label="Exact cylinder from selected mesh patch",
        operations=[
            {
                "id": "selected_cylinder",
                "type": "analytic_surface_patch",
                "surface": {
                    "kind": "cylinder",
                    "origin_mm": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "reference_direction": [1, 0, 0],
                    "radius_mm": 10,
                },
                "boundary_uv": [[0, 0], [1.5707963267948966, 0], [1.5707963267948966, 20], [0, 20]],
                "thickness_mm": 2,
            }
        ],
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result = job.result or {}
    child = db_session.get(ProjectVersion, result["version_id"])
    assert child is not None
    assert str(child.parent_version_id) == version_id
    assert child.provenance["replaced_history"] is True
    assert result["plan"]["expected_outputs"] == ["selected_cylinder"]
    assert child.provenance["bodies"][-1]["name"] == "selected_cylinder"
    logged = (
        db_session.query(Operation)
        .filter(Operation.project_version_id == child.id)
        .order_by(Operation.sequence_no)
        .all()
    )
    assert [row.operation_type for row in logged] == ["analytic_surface_patch"]
    assert logged[0].params["surface"]["kind"] == "cylinder"
    assert (
        db_session.query(Operation)
        .filter(Operation.project_version_id == version_id)
        .count()
        == parent_rows
    )


def test_edit_of_an_uploaded_model_without_history_is_rejected(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage
) -> None:
    project_id: str = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "manual"},
        headers=actor.headers,
    ).json()["id"]
    version_id: str = api_client.post(
        f"/api/v1/projects/{project_id}/versions", json={}, headers=actor.headers
    ).json()["id"]

    response = edit(
        api_client,
        actor,
        version_id,
        operations=[{"type": "set_dimensions", "target": "body", "width_mm": 10}],
    )
    assert response.status_code == 422
    assert "parametric history" in response.json()["error"]["message"]


def test_edit_requires_workspace_membership(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    from tests.integration.conftest import make_actor

    _, version_id = build_box(api_client, actor, db_session, storage)
    stranger = make_actor(db_session)
    response = edit(
        api_client,
        stranger,
        version_id,
        operations=[{"type": "set_dimensions", "target": "body", "width_mm": 10}],
    )
    assert response.status_code == 404
