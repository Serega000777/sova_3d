"""E23 (F-072/F-047): where a work comes from, and remixing it legally."""

from __future__ import annotations

from typing import Any

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.storage import S3Storage
from tests.integration.conftest import Actor, alembic_config
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_imports_api import project, run_all  # noqa: F401


def built(
    api_client: TestClient, actor: Actor, db_session: Session, storage: S3Storage, project_id: str
) -> str:
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": "Plate 60x40x8 mm", "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def set_license(api_client: TestClient, actor: Actor, project_id: str, **body: Any) -> Any:
    return api_client.put(
        f"/api/v1/projects/{project_id}/license", json=body, headers=actor.headers
    )


def test_migration_0013_adds_the_license_columns(migrated_db: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0012")
    columns = {c["name"] for c in inspect(migrated_db).get_columns("projects")}
    assert "license_id" not in columns
    command.upgrade(cfg, "head")
    columns = {c["name"] for c in inspect(migrated_db).get_columns("projects")}
    assert {"license_id", "attribution", "source_url", "remixed_from_project_id"} <= columns


def test_a_licence_needs_its_attribution_and_is_reported_with_its_terms(
    api_client: TestClient,
    actor: Actor,
    project: str,  # noqa: F811
) -> None:
    listing = api_client.get("/api/v1/licences", headers=actor.headers)
    assert listing.status_code == 200
    assert {lic["id"] for lic in listing.json()} >= {"CC-BY-4.0", "CC-BY-NC-SA-4.0", "CC0-1.0"}

    refused = set_license(api_client, actor, project, license_id="CC-BY-4.0")
    assert refused.status_code == 422 and "attribution" in refused.json()["error"]["message"]
    unknown = set_license(api_client, actor, project, license_id="WTFPL", attribution="x")
    assert unknown.status_code == 422

    ok = set_license(
        api_client,
        actor,
        project,
        license_id="CC-BY-NC-SA-4.0",
        attribution="Jane Maker",
        source_url="https://example.org/bracket",
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["license_id"] == "CC-BY-NC-SA-4.0"
    terms = api_client.get(f"/api/v1/projects/{project}/license", headers=actor.headers).json()
    assert terms["commercial_use"] is False and terms["derivatives"] is True
    assert terms["share_alike"] is True and terms["attribution_required"] is True
    assert terms["credits"] == ["Jane Maker (CC BY-NC-SA 4.0)"]
    assert any("Share-alike" in note for note in terms["notes"])
    assert terms["chain"][0]["source_url"] == "https://example.org/bracket"


def test_a_remix_carries_the_model_and_inherits_the_terms(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    head = built(api_client, actor, db_session, storage, project)
    set_license(api_client, actor, project, license_id="CC-BY-NC-SA-4.0", attribution="Jane Maker")

    remixed = api_client.post(f"/api/v1/projects/{project}/remix", json={}, headers=actor.headers)
    assert remixed.status_code == 201, remixed.text
    copy = remixed.json()
    assert copy["remixed_from_project_id"] == project
    assert copy["license_id"] == "CC-BY-NC-SA-4.0"  # share-alike keeps the licence
    assert copy["attribution"] == "Jane Maker (CC BY-NC-SA 4.0)"  # the credit line is written
    summary = api_client.get(f"/api/v1/projects/{copy['id']}", headers=actor.headers).json()
    new_head = summary["head_version"]
    assert new_head["label"].startswith("Remix of")
    assert new_head["provenance"]["remixed_from_version_id"] == head
    original = api_client.get(f"/api/v1/versions/{head}", headers=actor.headers).json()
    assert {a["role"]: a["asset_id"] for a in new_head["assets"]} == {
        a["role"]: a["asset_id"] for a in original["assets"]
    }

    # the chain and the strictest terms follow a remix of the remix
    again = api_client.post(
        f"/api/v1/projects/{copy['id']}/remix", json={"name": "Mine"}, headers=actor.headers
    )
    assert again.status_code == 201
    terms = api_client.get(
        f"/api/v1/projects/{again.json()['id']}/license", headers=actor.headers
    ).json()
    assert [link["name"] for link in terms["chain"]][1:] == [copy["name"], "imported"]
    assert terms["commercial_use"] is False
    assert "Jane Maker (CC BY-NC-SA 4.0)" in terms["credits"]


def test_no_derivatives_means_no_remix(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    built(api_client, actor, db_session, storage, project)
    set_license(api_client, actor, project, license_id="CC-BY-ND-4.0", attribution="Someone")
    refused = api_client.post(f"/api/v1/projects/{project}/remix", json={}, headers=actor.headers)
    assert refused.status_code == 422
    assert "no derivatives" in refused.json()["error"]["message"]


def test_a_permissive_licence_lets_the_remix_be_your_own_work(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    built(api_client, actor, db_session, storage, project)
    set_license(api_client, actor, project, license_id="CC-BY-4.0", attribution="Jane Maker")
    copy = api_client.post(
        f"/api/v1/projects/{project}/remix", json={}, headers=actor.headers
    ).json()
    assert copy["license_id"] is None  # your own work now
    assert copy["attribution"] == "Jane Maker (CC BY 4.0)"  # but the credit stays
    terms = api_client.get(f"/api/v1/projects/{copy['id']}/license", headers=actor.headers).json()
    assert terms["commercial_use"] is True and terms["share_alike"] is False
    assert terms["attribution_required"] is True
