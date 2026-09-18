"""T-090: one workspace cannot see or touch another's work.

The rule is stated once here and swept across every route that takes a resource id: a
non-member gets 404, never 403 and never a leak — the existence of someone else's project
is itself information. A new endpoint that forgets `require_workspace_role` fails the
coverage test at the bottom, not a user's privacy.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, ProjectVersion
from app.models.core import Units, WorkspaceRole
from app.models.versioning import AssetKind, AssetRole
from app.services import jobs, projects, scanning
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor


@pytest.fixture
def owned(db_session: Session, actor: Actor, storage: S3Storage) -> dict[str, Any]:
    """A workspace with one of everything, owned by `actor`."""
    project = projects.create_project(
        db_session, user_id=actor.user.id, workspace_id=actor.workspace.id, name="private"
    )
    asset = Asset(
        workspace_id=actor.workspace.id,
        kind=AssetKind.original,
        sha256="b" * 64,
        storage_key=f"ws/{actor.workspace.id}/assets/bb/{'b' * 64}.stl",
        mime="model/stl",
        format="stl",
        byte_size=84,
        units=Units.mm,
    )
    db_session.add(asset)
    db_session.flush()
    version = projects.create_version_internal(
        db_session,
        project_id=project.id,
        assets={AssetRole.model: asset.id},
        created_by=actor.user.id,
    )
    job = jobs.enqueue(
        db_session,
        workspace_id=actor.workspace.id,
        job_type="export",
        input={},
        created_by=actor.user.id,
    )
    scan = scanning.create_session(
        db_session, user_id=actor.user.id, workspace_id=actor.workspace.id
    )
    request = db_session.execute(
        ProjectVersion.__table__.select().where(ProjectVersion.id == version.id)
    ).first()
    assert request is not None
    return {
        "project": str(project.id),
        "version": str(version.id),
        "asset": str(asset.id),
        "job": str(job.id),
        "scan": str(scan.id),
        "workspace": str(actor.workspace.id),
    }


def routes(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any] | None]]:
    """(method, path, json body) for every route that takes a workspace-owned id."""
    project, version, asset, job, scan = (
        ids["project"],
        ids["version"],
        ids["asset"],
        ids["job"],
        ids["scan"],
    )
    return [
        ("GET", f"/api/v1/projects?workspace_id={ids['workspace']}", None),
        ("GET", f"/api/v1/projects/{project}", None),
        ("PATCH", f"/api/v1/projects/{project}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/projects/{project}", None),
        ("GET", f"/api/v1/projects/{project}/versions", None),
        ("POST", f"/api/v1/projects/{project}/versions", {}),
        ("GET", f"/api/v1/versions/{version}", None),
        ("GET", f"/api/v1/versions/{version}/lineage", None),
        ("POST", f"/api/v1/versions/{version}/finalize", None),
        ("POST", f"/api/v1/models/{version}/repair", None),
        ("POST", f"/api/v1/models/{version}/analyze-print", {}),
        ("POST", f"/api/v1/models/{version}/optimize-print", {}),
        ("GET", f"/api/v1/models/{version}/print-analyses", None),
        ("POST", f"/api/v1/models/{version}/exports", {"format": "stl"}),
        (
            "POST",
            f"/api/v1/models/{version}/edits",
            {"operations": [{"type": "set_dimensions", "target": "body", "width_mm": 10}]},
        ),
        (
            "POST",
            f"/api/v1/projects/{project}/ai-commands",
            {"prompt": "Box 10x10x10 mm"},
        ),
        ("GET", f"/api/v1/projects/{project}/ai-requests", None),
        ("GET", f"/api/v1/jobs/{job}", None),
        ("POST", f"/api/v1/jobs/{job}/cancel", None),
        ("GET", f"/api/v1/assets/{asset}/download", None),
        ("GET", f"/api/v1/scans/{scan}", None),
        ("GET", f"/api/v1/scans/{scan}/frames", None),
        ("POST", f"/api/v1/scans/{scan}/frames", {"asset_id": asset, "sequence_no": 0}),
        ("PATCH", f"/api/v1/scans/{scan}/capture-stats", {"stats": {}}),
        ("POST", f"/api/v1/scans/{scan}/finalize", {}),
        ("POST", f"/api/v1/scans/{scan}/accept", {}),
        ("POST", f"/api/v1/scans/{scan}/cancel", None),
        ("GET", f"/api/v1/usage?workspace_id={ids['workspace']}", None),
    ]


def test_a_stranger_gets_404_from_every_route(
    api_client: TestClient, actor: Actor, db_session: Session, owned: dict[str, str]
) -> None:
    stranger = make_actor(db_session)
    for method, path, body in routes(owned):
        response = api_client.request(method, path, json=body, headers=stranger.headers)
        assert response.status_code == 404, f"{method} {path} leaked ({response.status_code})"
        assert response.json()["error"]["code"] == "not_found", f"{method} {path}"
        # The body must not confirm what it refuses to serve.
        assert "private" not in response.text


def test_the_owner_is_not_locked_out_by_the_same_checks(
    api_client: TestClient, actor: Actor, owned: dict[str, str]
) -> None:
    """The sweep would also pass if everything 404'd for everyone; it must not.

    DELETE goes last: it removes the project the other routes address.
    """
    ordered = sorted(routes(owned), key=lambda route: route[0] == "DELETE")
    for method, path, body in ordered:
        response = api_client.request(method, path, json=body, headers=actor.headers)
        assert response.status_code != 404, f"{method} {path} refused its owner"


def test_no_token_and_a_bad_token_are_both_refused(
    api_client: TestClient, owned: dict[str, str]
) -> None:
    for headers in ({}, {"Authorization": "Bearer pai_not_a_real_token"}):
        response = api_client.get(f"/api/v1/projects/{owned['project']}", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


def test_a_viewer_cannot_change_anything(
    api_client: TestClient, actor: Actor, db_session: Session, owned: dict[str, str]
) -> None:
    """Membership is not permission: a viewer reads, an editor writes."""
    viewer = make_actor(db_session, workspace=actor.workspace, role=WorkspaceRole.viewer)
    assert (
        api_client.get(f"/api/v1/projects/{owned['project']}", headers=viewer.headers).status_code
        == 200
    )
    blocked = api_client.post(
        f"/api/v1/projects/{owned['project']}/ai-commands",
        json={"prompt": "Box 10x10x10 mm"},
        headers=viewer.headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "forbidden"


def test_an_id_from_another_workspace_is_never_accepted_as_input(
    api_client: TestClient, actor: Actor, db_session: Session, owned: dict[str, str]
) -> None:
    """Cross-workspace stitching: my scan must not swallow someone else's asset."""
    stranger = make_actor(db_session)
    their_scan = scanning.create_session(
        db_session, user_id=stranger.user.id, workspace_id=stranger.workspace.id
    )
    response = api_client.post(
        f"/api/v1/scans/{their_scan.id}/frames",
        json={"asset_id": owned["asset"], "sequence_no": 0},
        headers=stranger.headers,
    )
    assert response.status_code == 404


def test_every_id_route_is_in_the_sweep(owned: dict[str, str]) -> None:
    """A new endpoint taking a resource id must be added here, or this fails."""
    from app.main import create_app
    from tests.integration.conftest import test_s3_settings as make_settings

    app = create_app(make_settings("postgresql+psycopg://u:p@localhost/x"))
    covered = {path.split("?")[0] for _, path, _ in routes(owned)}

    def normalise(path: str) -> str:
        for value in owned.values():
            path = path.replace(value, "{id}")
        return path

    swept = {normalise(path) for path in covered}
    missing = []
    for route in app.routes:
        template: str = getattr(route, "path", "")
        methods: set[str] = getattr(route, "methods", set())
        if not template.startswith("/api/v1/") or "{" not in template:
            continue
        if template.startswith("/api/v1/ai-requests"):
            continue  # covered by the AI command suite, which owns request ids
        shape = template.replace("{project_id}", "{id}").replace("{version_id}", "{id}")
        shape = shape.replace("{job_id}", "{id}").replace("{asset_id}", "{id}")
        shape = shape.replace("{scan_id}", "{id}").replace("{profile_id}", "{id}")
        shape = shape.replace("{analysis_id}", "{id}").replace("{upload_id}", "{id}")
        if shape not in swept and methods & {"GET", "POST", "PATCH", "DELETE"}:
            missing.append(f"{sorted(methods)} {template}")
    assert not missing, f"routes missing from the authorization sweep: {missing}"
