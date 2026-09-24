"""E29 (F-004/F-065): a kept version goes on the shelf under a licence; someone else takes
it into their own workspace with the credit written; creators have handles and followers."""

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


def build(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project_id: str,
    prompt: str = "Box 40x20x8 mm with a 5 mm hole",
) -> str:
    response = api_client.post(
        f"/api/v1/projects/{project_id}/ai-commands",
        json={"prompt": prompt, "units": "mm", "target": "print"},
        headers=actor.headers,
    )
    assert response.status_code == 202, response.text
    (job,) = run_all(db_session, storage)
    assert job.status is JobStatus.succeeded, job.error
    return str((job.result or {})["version_id"])


def publish(
    api_client: TestClient, actor: Actor, project_id: str, **overrides: Any
) -> dict[str, Any]:
    body = {
        "title": "Cable clip 40 mm",
        "description": "A clip for a 5 mm cable, prints flat",
        "category": "print",
        "tags": ["cable", "clip", "desk"],
        "price_cents": 0,
        "license_id": "CC-BY-4.0",
        **overrides,
    }
    response = api_client.post(
        f"/api/v1/projects/{project_id}/listings", json=body, headers=actor.headers
    )
    assert response.status_code == 201, response.text
    listing: dict[str, Any] = response.json()
    return listing


def test_publish_needs_a_licence_and_a_kept_version(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    empty = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={"title": "nothing yet", "license_id": "CC0-1.0"},
        headers=actor.headers,
    )
    assert empty.status_code == 422
    build(api_client, actor, db_session, storage, project)
    unlicensed = api_client.post(
        f"/api/v1/projects/{project}/listings", json={"title": "Clip"}, headers=actor.headers
    )
    assert unlicensed.status_code == 422
    assert "licence" in unlicensed.json()["error"]["message"]

    listing = publish(api_client, actor, project)
    assert listing["status"] == "published" and listing["license_name"] == "CC BY 4.0"
    assert listing["creator_handle"] and listing["model_asset_id"]
    assert listing["summary"]["size_mm"] == [40.0, 20.0, 8.0]
    # the project now says what it is offered under
    summary = api_client.get(f"/api/v1/projects/{project}", headers=actor.headers).json()
    assert summary["license_id"] == "CC-BY-4.0"
    # the same version cannot be listed twice
    again = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={"title": "Clip again", "license_id": "CC0-1.0"},
        headers=actor.headers,
    )
    assert again.status_code == 409


def test_search_finds_by_words_category_and_price(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    other = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "second"},
        headers=actor.headers,
    ).json()
    build(
        api_client, actor, db_session, storage, other["id"], "Cylinder diameter 30 mm, height 12 mm"
    )
    priced = publish(
        api_client,
        actor,
        other["id"],
        title="Coaster",
        description="A round coaster for the desk",
        category="other",
        tags=["desk"],
        price_cents=350,
    )

    def ids(**params: Any) -> list[str]:
        response = api_client.get(
            "/api/v1/marketplace/listings", params=params, headers=actor.headers
        )
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()]

    assert set(ids()) >= {listing["id"], priced["id"]}
    assert ids(q="cable clip") == [listing["id"]]
    assert ids(q="desk") == [priced["id"], listing["id"]]  # newest first
    assert ids(category="other") == [priced["id"]]
    assert listing["id"] in ids(free=True) and priced["id"] not in ids(free=True)
    assert ids(q="desk", sort="cheapest")[0] == listing["id"]
    assert ids(creator=listing["creator_handle"], q="coaster") == [priced["id"]]


def test_someone_else_takes_a_free_listing_home_with_the_credit(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    buyer = make_actor(db_session)

    response = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    acquired = response.json()
    assert acquired["order"]["status"] == "completed"
    assert acquired["order"]["price_cents"] == 0 and acquired["order"]["payment_provider"] is None

    copy = api_client.get(f"/api/v1/projects/{acquired['project_id']}", headers=buyer.headers)
    assert copy.status_code == 200, copy.text
    theirs = copy.json()
    assert theirs["name"] == "Cable clip 40 mm" and theirs["license_id"] == "CC-BY-4.0"
    assert theirs["attribution"] == f"Cable clip 40 mm by @{listing['creator_handle']} (CC BY 4.0)"
    assert theirs["remixed_from_project_id"] == project
    head = theirs["head_version"]
    assert head is not None and head["state"] == "finalized"
    assert head["provenance"]["operation"] == "acquire"
    assert head["provenance"]["listing_id"] == listing["id"]
    # the files came along — as the buyer's own assets — and so did the parametric history
    versions = api_client.get(
        f"/api/v1/projects/{acquired['project_id']}/versions", headers=buyer.headers
    ).json()
    roles = {link["role"] for link in versions[0]["assets"]}
    assert {"model", "source"} <= roles
    for link in versions[0]["assets"]:
        download = api_client.get(
            f"/api/v1/assets/{link['asset_id']}/download", headers=buyer.headers
        )
        assert download.status_code in (200, 307), download.text
    edit = api_client.post(
        f"/api/v1/models/{head['id']}/edits",
        json={
            "operations": [
                {"type": "set_parameter", "operation": "body", "parameter": "width_mm", "value": 50}
            ]
        },
        headers=buyer.headers,
    )
    assert edit.status_code == 202, edit.text  # they can keep working on it

    # the creator cannot take their own listing into the workspace it lives in
    own = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(actor.workspace.id)},
        headers=actor.headers,
    )
    assert own.status_code == 422
    # taking it again gives the same copy back
    again = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    ).json()
    assert again["project_id"] == acquired["project_id"]
    assert (
        api_client.get(f"/api/v1/listings/{listing['id']}", headers=buyer.headers).json()[
            "downloads"
        ]
        == 1
    )
    orders = api_client.get("/api/v1/me/orders", headers=buyer.headers).json()
    assert [o["item_id"] for o in orders] == [listing["id"]]


def test_priced_listings_need_a_payment_provider(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project, price_cents=499)
    buyer = make_actor(db_session)

    # local/CI settings default PAYMENTS_PROVIDER to "stub" so demos can buy things out of
    # the box; force "none" here to exercise the refusal this test is actually about.
    settings = api_client.app.state.settings  # type: ignore[attr-defined]
    api_client.app.state.settings = settings.model_copy(update={"payments_provider": "none"})  # type: ignore[attr-defined]
    refused = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    )
    assert refused.status_code == 402
    assert refused.json()["error"]["code"] == "payments_not_enabled"

    api_client.app.state.settings = settings.model_copy(update={"payments_provider": "stub"})  # type: ignore[attr-defined]
    try:
        bought = api_client.post(
            f"/api/v1/listings/{listing['id']}/acquire",
            json={"workspace_id": str(buyer.workspace.id)},
            headers=buyer.headers,
        )
    finally:
        api_client.app.state.settings = settings  # type: ignore[attr-defined]
    assert bought.status_code == 201, bought.text
    order = bought.json()["order"]
    assert order["price_cents"] == 499 and order["payment_provider"] == "stub"
    assert order["status"] == "completed"


def test_creators_have_handles_followers_and_a_feed(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    mine = api_client.put(
        "/api/v1/me/creator-profile",
        json={"handle": "Desk-Maker", "display_name": "Desk Maker", "bio": "small useful things"},
        headers=actor.headers,
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["handle"] == "desk-maker"
    bad = api_client.put(
        "/api/v1/me/creator-profile", json={"handle": "no spaces!"}, headers=actor.headers
    )
    assert bad.status_code == 422

    fan = make_actor(db_session)
    taken = api_client.put(
        "/api/v1/me/creator-profile", json={"handle": "desk-maker"}, headers=fan.headers
    )
    assert taken.status_code == 409
    selfie = api_client.post("/api/v1/creators/desk-maker/follow", headers=actor.headers)
    assert selfie.status_code == 422

    followed = api_client.post("/api/v1/creators/desk-maker/follow", headers=fan.headers)
    assert followed.status_code == 200 and followed.json()["following"] is True
    assert followed.json()["followers"] == 1
    page = api_client.get("/api/v1/creators/desk-maker", headers=fan.headers).json()
    assert page["profile"]["bio"] == "small useful things" and page["profile"]["following"]
    assert page["listings"] == []

    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    feed = api_client.get("/api/v1/marketplace/feed", headers=fan.headers).json()
    assert [item["id"] for item in feed] == [listing["id"]]
    assert [
        c["handle"] for c in api_client.get("/api/v1/me/following", headers=fan.headers).json()
    ] == ["desk-maker"]

    unfollowed = api_client.delete("/api/v1/creators/desk-maker/follow", headers=fan.headers)
    assert unfollowed.status_code == 200 and unfollowed.json()["followers"] == 0
    assert api_client.get("/api/v1/marketplace/feed", headers=fan.headers).json() == []


def test_a_withdrawn_listing_is_the_creators_alone(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    patched = api_client.patch(
        f"/api/v1/listings/{listing['id']}",
        json={"status": "withdrawn", "price_cents": 200, "tags": ["Cable", "cable ", "x"]},
        headers=actor.headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "withdrawn" and patched.json()["tags"] == ["cable", "x"]
    stranger = make_actor(db_session)
    assert (
        api_client.get(f"/api/v1/listings/{listing['id']}", headers=stranger.headers).status_code
        == 404
    )
    assert api_client.get("/api/v1/marketplace/listings", headers=stranger.headers).json() == []
    assert (
        api_client.get(f"/api/v1/listings/{listing['id']}", headers=actor.headers).status_code
        == 200
    )
    mine = api_client.get("/api/v1/me/listings", headers=actor.headers).json()
    assert [item["id"] for item in mine] == [listing["id"]]
    # only the creator edits it
    foreign = api_client.patch(
        f"/api/v1/listings/{listing['id']}", json={"title": "mine now"}, headers=stranger.headers
    )
    assert foreign.status_code == 404
