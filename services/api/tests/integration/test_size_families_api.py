"""Reference 81: persisted exact S/M/L family over verified preview versions."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers manual_edit
from app.models import Project, ProjectVersion
from app.models.core import WorkspaceRole
from app.models.versioning import VersionState
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import cleanup_keys, kernel_or_fake, run_all  # noqa: F401
from tests.integration.test_preview_versions import build


def preview_size(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    source_version_id: str,
    label: str,
    width_mm: float,
) -> str:
    accepted = api_client.post(
        f"/api/v1/models/{source_version_id}/edits",
        json={
            "operations": [
                {
                    "type": "set_dimensions",
                    "target": "body",
                    "width_mm": width_mm,
                    "depth_mm": 20,
                    "height_mm": 8,
                }
            ],
            "label": f"Size {label}",
            "preview": True,
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (job,) = run_all(db_session, storage)
    assert job.status.value == "succeeded", job.error
    result = job.result or {}
    assert result["preview"] is True
    return str(result["version_id"])


def family_body(source_version_id: str, versions: dict[str, str]) -> dict[str, object]:
    return {
        "source_version_id": source_version_id,
        "selected_label": "M",
        "members": [{"label": label, "version_id": versions[label]} for label in ("S", "M", "L")],
    }


def test_create_list_and_select_persisted_size_family(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, source_version_id = build(api_client, actor, db_session, storage)
    versions = {
        "S": preview_size(api_client, actor, db_session, storage, source_version_id, "S", 40),
        "M": preview_size(api_client, actor, db_session, storage, source_version_id, "M", 40),
        "L": preview_size(api_client, actor, db_session, storage, source_version_id, "L", 40),
    }

    created = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=family_body(source_version_id, versions),
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    family = created.json()
    assert family["source_version_id"] == source_version_id
    assert family["selected_label"] == "M"
    assert [(row["label"], row["width_mm"]) for row in family["members"]] == [
        ("S", 40.0),
        ("M", 40.0),
        ("L", 40.0),
    ]
    assert all(
        db_session.get(ProjectVersion, version_id).state is VersionState.finalized
        for version_id in versions.values()
    )
    project = db_session.get(Project, project_id)
    assert project is not None and str(project.head_version_id) == versions["M"]

    retried = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=family_body(source_version_id, versions),
        headers=actor.headers,
    )
    assert retried.status_code == 201
    assert retried.json()["id"] == family["id"]

    listed = api_client.get(f"/api/v1/projects/{project_id}/size-families", headers=actor.headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [family["id"]]

    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    refused_select = api_client.post(
        f"/api/v1/projects/{project_id}/size-families/{family['id']}/select",
        json={"label": "L"},
        headers=viewer.headers,
    )
    assert refused_select.status_code == 403

    selected = api_client.post(
        f"/api/v1/projects/{project_id}/size-families/{family['id']}/select",
        json={"label": "L"},
        headers=actor.headers,
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_label"] == "L"
    db_session.refresh(project)
    assert str(project.head_version_id) == versions["L"]


def test_family_rejects_non_editor_duplicate_and_stale_source(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    cleanup_keys: list[str],  # noqa: F811
) -> None:
    project_id, source_version_id = build(api_client, actor, db_session, storage)
    versions = {
        "S": preview_size(api_client, actor, db_session, storage, source_version_id, "S", 40),
        "M": preview_size(api_client, actor, db_session, storage, source_version_id, "M", 40),
        "L": preview_size(api_client, actor, db_session, storage, source_version_id, "L", 40),
    }
    viewer = make_actor(db_session, role=WorkspaceRole.viewer, workspace=actor.workspace)
    refused = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=family_body(source_version_id, versions),
        headers=viewer.headers,
    )
    assert refused.status_code == 403

    stranger = make_actor(db_session)
    assert (
        api_client.get(
            f"/api/v1/projects/{project_id}/size-families", headers=stranger.headers
        ).status_code
        == 404
    )
    foreign = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=family_body(source_version_id, versions),
        headers=stranger.headers,
    )
    assert foreign.status_code == 404

    duplicate = family_body(source_version_id, versions)
    duplicate["members"] = [
        {"label": "S", "version_id": versions["S"]},
        {"label": "M", "version_id": versions["S"]},
        {"label": "L", "version_id": versions["L"]},
    ]
    bad = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=duplicate,
        headers=actor.headers,
    )
    assert bad.status_code == 422

    project = db_session.get(Project, project_id)
    assert project is not None
    project.head_version_id = versions["S"]
    db_session.flush()
    stale = api_client.post(
        f"/api/v1/projects/{project_id}/size-families",
        json=family_body(source_version_id, versions),
        headers=actor.headers,
    )
    assert stale.status_code == 409
