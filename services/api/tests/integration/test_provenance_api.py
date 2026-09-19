"""E32 (F-079): the provenance graph — versions, commands, origins, listings, derived work."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def command(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project_id: str,
    prompt: str,
) -> dict[str, Any]:
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": prompt, "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    result: dict[str, Any] = job.result or {}
    return result


def test_the_graph_joins_versions_commands_listings_and_the_buyers_copy(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    first = command(api_client, actor, db_session, storage, project, "Box 40x20x8 mm")
    second = command(api_client, actor, db_session, storage, project, "скругли рёбра 1 мм")
    listing = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={"title": "Rounded box", "license_id": "CC-BY-4.0"},
        headers=actor.headers,
    ).json()
    buyer = make_actor(db_session)
    api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    )

    response = api_client.get(f"/api/v1/projects/{project}/graph", headers=actor.headers)
    assert response.status_code == 200, response.text
    graph = response.json()
    kinds = {node["kind"] for node in graph["nodes"]}
    assert {"version", "command", "listing", "derived"} <= kinds

    versions = [n for n in graph["nodes"] if n["kind"] == "version"]
    assert [v["sequence_no"] for v in versions] == [1, 2]
    assert versions[0]["operation"] == "ai_command" and versions[0]["operation_label"]
    assert versions[1]["head"] is True and versions[0]["head"] is False
    edges = {(e["kind"], e["source"], e["target"]) for e in graph["edges"]}
    assert ("parent", f"version:{first['version_id']}", f"version:{second['version_id']}") in edges
    commands = [n for n in graph["nodes"] if n["kind"] == "command"]
    assert {c["title"] for c in commands} == {"Box 40x20x8 mm", "скругли рёбра 1 мм"}
    assert all(
        ("made_by", c["id"], f"version:{v['version_id']}") in edges
        for c, v in zip(commands, [first, second], strict=True)
    )
    shelf = next(n for n in graph["nodes"] if n["kind"] == "listing")
    assert shelf["title"] == "Rounded box" and shelf["downloads"] == 1
    assert ("listed_as", f"version:{second['version_id']}", shelf["id"]) in edges
    # the buyer's copy is theirs: it shows as taken, not by name
    taken = next(n for n in graph["nodes"] if n["kind"] == "derived")
    assert taken["visible"] is False and taken["title"] == "taken by another maker"
    assert graph["summary"]["versions"] == 2 and graph["summary"]["licence"]["id"] == "CC-BY-4.0"
    assert graph["summary"]["operations"] == {"ai_command": 2}

    # from the buyer's side the origin is the listing, with the creator credited
    theirs = api_client.get("/api/v1/me/orders", headers=buyer.headers).json()[0]["project_id"]
    mine = api_client.get(f"/api/v1/projects/{theirs}/graph", headers=buyer.headers).json()
    origin = next(n for n in mine["nodes"] if n["kind"] == "origin")
    assert origin["title"] == "Rounded box" and origin["creator_handle"]
    assert any(e["kind"] == "acquired_from" for e in mine["edges"])
    assert mine["summary"]["credits"]


def test_a_remix_shows_where_it_came_from_and_the_source_shows_the_remix(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    command(api_client, actor, db_session, storage, project, "Box 40x20x8 mm")
    api_client.put(
        f"/api/v1/projects/{project}/license", json={"license_id": "CC0-1.0"}, headers=actor.headers
    )
    remix = api_client.post(f"/api/v1/projects/{project}/remix", json={}, headers=actor.headers)
    assert remix.status_code == 201, remix.text
    copy_id = remix.json()["id"]
    theirs = api_client.get(f"/api/v1/projects/{copy_id}/graph", headers=actor.headers).json()
    origin = next(n for n in theirs["nodes"] if n["kind"] == "origin")
    assert origin["title"] == "imported" and origin["visible"] is True
    assert any(e["kind"] == "remixed_from" for e in theirs["edges"])
    source = api_client.get(f"/api/v1/projects/{project}/graph", headers=actor.headers).json()
    derived = [n for n in source["nodes"] if n["kind"] == "derived"]
    assert [d["remix"] for d in derived] == [True] and derived[0]["project_id"] == copy_id
