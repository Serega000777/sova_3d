"""E29 (F-004/F-065): listings, acquisition, creator profiles, follows and collections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.jobs.handlers  # noqa: F401 — registers handlers
from app.models.execution import JobStatus
from app.models.printing import AnalysisKind, PrintAnalysisRecord
from app.models.versioning import AssetRole, ProjectVersion
from app.services import marketplace, projects
from app.storage import S3Storage
from tests.integration.conftest import Actor, make_actor
from tests.integration.test_ai_commands import kernel_or_fake  # noqa: F401 — fake kernel
from tests.integration.test_facade_api import house_box, rectangular_house
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
        "domain": "printable",
        "subcategory": "cable-management",
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
    version_id = build(api_client, actor, db_session, storage, project)
    queued = api_client.post(f"/api/v1/versions/{version_id}/thumbnail", headers=actor.headers)
    assert queued.status_code == 202, queued.text
    (rendered,) = run_all(db_session, storage)
    assert rendered.status is JobStatus.succeeded, rendered.error
    thumbnail_id = str((rendered.result or {})["asset_id"])
    unlicensed = api_client.post(
        f"/api/v1/projects/{project}/listings", json={"title": "Clip"}, headers=actor.headers
    )
    assert unlicensed.status_code == 422
    assert "licence" in unlicensed.json()["error"]["message"]

    wrong_taxonomy = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={
            "title": "Wrong shelf",
            "domain": "yard",
            "subcategory": "cable-management",
            "license_id": "CC-BY-4.0",
        },
        headers=actor.headers,
    )
    assert wrong_taxonomy.status_code == 422
    assert wrong_taxonomy.json()["error"]["details"]["domain"] == "yard"

    listing = publish(api_client, actor, project)
    assert listing["status"] == "published" and listing["license_name"] == "CC BY 4.0"
    assert listing["domain"] == "printable"
    assert listing["subcategory"] == "cable-management"
    assert listing["creator_handle"] and listing["model_asset_id"]
    assert listing["thumbnail_asset_id"] == thumbnail_id
    assert {row["angle"] for row in listing["thumbnails"]} == {"front", "iso", "top"}
    iso_thumbnail = next(row for row in listing["thumbnails"] if row["angle"] == "iso")
    assert iso_thumbnail["asset_id"] == thumbnail_id
    assert listing["summary"]["size_mm"] == [40.0, 20.0, 8.0]
    offered = {parameter["key"]: parameter for parameter in listing["parameters"]}
    assert offered["body.width_mm"]["value"] == 40.0
    assert offered["body.width_mm"]["unit"] == "mm"
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
    assert marketplace.has_2d_plan_evidence({"floor_plan": {"id": "forged"}}) is False
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    other = api_client.post(
        "/api/v1/projects",
        json={"workspace_id": str(actor.workspace.id), "name": "second"},
        headers=actor.headers,
    ).json()
    other_version_id = build(
        api_client, actor, db_session, storage, other["id"], "Cylinder diameter 30 mm, height 12 mm"
    )
    other_version = db_session.get(ProjectVersion, uuid.UUID(other_version_id))
    assert other_version is not None
    plan_version = projects.create_version(
        db_session,
        user_id=actor.user.id,
        project_id=uuid.UUID(other["id"]),
        parent_version_id=other_version.id,
        label="Coaster with a plan",
        provenance={
            **(other_version.provenance or {}),
            "floor_plan": {
                "id": "marketplace-plan-evidence",
                "name": "Measured plan",
                "walls": [{"a": [0, 0], "b": [1000, 0], "thickness_mm": 100}],
            },
        },
        assets={
            link.role: link.asset_id
            for link in other_version.assets
            if link.role in {AssetRole.source, AssetRole.model, AssetRole.export}
        },
    )
    priced = publish(
        api_client,
        actor,
        other["id"],
        version_id=str(plan_version.id),
        title="Coaster",
        description="A round clip coaster for the desk",
        category="other",
        domain="element",
        subcategory="home-decor",
        tags=["desk"],
        price_cents=350,
    )
    db_session.add(
        PrintAnalysisRecord(
            workspace_id=actor.workspace.id,
            project_version_id=plan_version.id,
            kind=AnalysisKind.analysis,
            score=Decimal("96.0"),
            status="green",
            report={"source": "marketplace-filter-test"},
        )
    )
    db_session.flush()

    def ids(**params: Any) -> list[str]:
        response = api_client.get(
            "/api/v1/marketplace/listings", params=params, headers=actor.headers
        )
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()]

    assert set(ids()) >= {listing["id"], priced["id"]}
    assert ids(q="cable clip") == [listing["id"]]
    assert ids(q="desk") == [priced["id"], listing["id"]]  # newest first
    assert ids(q="clip") == [priced["id"], listing["id"]]  # newest first
    assert ids(q="clip", sort="relevant") == [listing["id"], priced["id"]]
    assert ids(q="coaster", sort="relevant") == [priced["id"]]
    assert ids(category="other") == [priced["id"]]
    assert ids(domain="printable") == [listing["id"]]
    assert ids(domain="element", subcategory="home-decor") == [priced["id"]]
    assert listing["id"] in ids(free=True) and priced["id"] not in ids(free=True)
    assert ids(min_price_cents=100) == [priced["id"]]
    assert ids(max_price_cents=100) == [listing["id"]]
    assert ids(min_price_cents=300, max_price_cents=400) == [priced["id"]]
    assert set(ids(format="stl")) >= {listing["id"], priced["id"]}
    assert ids(format="3mf") == []
    assert ids(editable=True) == [listing["id"]]
    assert ids(has_2d_plan=True) == [priced["id"]]
    assert ids(print_ready=True) == [priced["id"]]
    assert ids(q="desk", sort="cheapest")[0] == listing["id"]
    assert ids(creator=listing["creator_handle"], q="coaster") == [priced["id"]]
    shown = api_client.get(f"/api/v1/listings/{listing['id']}", headers=actor.headers).json()
    assert "stl" in shown["available_formats"]
    assert shown["editable"] is True
    assert shown["has_2d_plan"] is False
    assert shown["print_ready"] is False
    priced_shown = api_client.get(f"/api/v1/listings/{priced['id']}", headers=actor.headers).json()
    assert priced_shown["has_2d_plan"] is True
    assert priced_shown["print_ready"] is True

    # F-046: compatibility is based on the immutable version's measured bounds, not tags.
    assert ids(max_width_mm=35, max_depth_mm=35, max_height_mm=15) == [priced["id"]]
    assert ids(max_width_mm=20, max_depth_mm=40, max_height_mm=8) == []
    assert ids(
        max_width_mm=20,
        max_depth_mm=40,
        max_height_mm=8,
        rotate_to_fit=True,
    ) == [listing["id"]]
    incomplete_rotation = api_client.get(
        "/api/v1/marketplace/listings",
        params={"max_width_mm": 40, "rotate_to_fit": True},
        headers=actor.headers,
    )
    assert incomplete_rotation.status_code == 422
    reversed_price_range = api_client.get(
        "/api/v1/marketplace/listings",
        params={"min_price_cents": 400, "max_price_cents": 300},
        headers=actor.headers,
    )
    assert reversed_price_range.status_code == 422
    assert reversed_price_range.json()["error"]["message"] == (
        "minimum price cannot exceed maximum price"
    )

    facets_response = api_client.get("/api/v1/marketplace/facets", headers=actor.headers)
    assert facets_response.status_code == 200, facets_response.text
    domain_rows = facets_response.json()["domains"]
    assert [facet["id"] for facet in domain_rows] == [
        "figure",
        "element",
        "house",
        "yard",
        "printable",
        "other",
    ]
    facets = {facet["id"]: facet for facet in domain_rows}
    assert set(facets) == {"figure", "element", "house", "yard", "printable", "other"}
    assert facets["printable"]["count"] == 1
    assert facets["printable"]["label_ru"] == "Для печати"
    assert facets["printable"]["order"] == 4
    printable_children = {child["id"]: child for child in facets["printable"]["subcategories"]}
    assert printable_children["cable-management"] == {
        "id": "cable-management",
        "label_en": "Cable management",
        "label_ru": "Крепления для кабелей",
        "order": 1,
        "count": 1,
    }
    assert printable_children["replacement-parts"]["count"] == 0
    assert facets["element"]["count"] == 1
    element_children = {child["id"]: child for child in facets["element"]["subcategories"]}
    assert element_children["home-decor"]["count"] == 1
    assert element_children["facade"]["count"] == 0
    malformed = api_client.get(
        "/api/v1/marketplace/listings",
        params={"subcategory": "Home Decor"},
        headers=actor.headers,
    )
    assert malformed.status_code == 422

    incompatible_patch = api_client.patch(
        f"/api/v1/listings/{listing['id']}",
        json={"domain": "yard"},
        headers=actor.headers,
    )
    assert incompatible_patch.status_code == 422
    compatible_patch = api_client.patch(
        f"/api/v1/listings/{listing['id']}",
        json={"domain": "element", "subcategory": "facade"},
        headers=actor.headers,
    )
    assert compatible_patch.status_code == 200, compatible_patch.text
    assert compatible_patch.json()["domain"] == "element"
    assert compatible_patch.json()["subcategory"] == "facade"


def test_favorites_are_private_idempotent_and_removable(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    other = make_actor(db_session)

    for _ in range(2):
        saved = api_client.post(
            f"/api/v1/marketplace/favorites/{listing['id']}", headers=actor.headers
        )
        assert saved.status_code == 201, saved.text
    mine = api_client.get("/api/v1/marketplace/favorites", headers=actor.headers)
    assert mine.status_code == 200, mine.text
    assert [row["id"] for row in mine.json()] == [listing["id"]]
    theirs = api_client.get("/api/v1/marketplace/favorites", headers=other.headers)
    assert theirs.status_code == 200, theirs.text
    assert theirs.json() == []

    for _ in range(2):
        removed = api_client.delete(
            f"/api/v1/marketplace/favorites/{listing['id']}", headers=actor.headers
        )
        assert removed.status_code == 204, removed.text
    assert api_client.get("/api/v1/marketplace/favorites", headers=actor.headers).json() == []


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

    unavailable = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={
            "workspace_id": str(buyer.workspace.id),
            "configuration": [{"operation": "body", "parameter": "radius_mm", "value": 55}],
        },
        headers=buyer.headers,
    )
    assert unavailable.status_code == 422
    out_of_range = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={
            "workspace_id": str(buyer.workspace.id),
            "configuration": [{"operation": "body", "parameter": "width_mm", "value": 20_000}],
        },
        headers=buyer.headers,
    )
    assert out_of_range.status_code == 422
    assert api_client.get("/api/v1/me/orders", headers=buyer.headers).json() == []

    response = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={
            "workspace_id": str(buyer.workspace.id),
            "configuration": [{"operation": "body", "parameter": "width_mm", "value": 55}],
        },
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    acquired = response.json()
    assert acquired["order"]["status"] == "completed"
    assert acquired["order"]["price_cents"] == 0 and acquired["order"]["payment_provider"] is None
    assert acquired["configuration_job_id"]
    (configured,) = run_all(db_session, storage)
    assert configured.status is JobStatus.succeeded, configured.error

    copy = api_client.get(f"/api/v1/projects/{acquired['project_id']}", headers=buyer.headers)
    assert copy.status_code == 200, copy.text
    theirs = copy.json()
    assert theirs["name"] == "Cable clip 40 mm" and theirs["license_id"] == "CC-BY-4.0"
    assert theirs["attribution"] == f"Cable clip 40 mm by @{listing['creator_handle']} (CC BY 4.0)"
    assert theirs["remixed_from_project_id"] == project
    head = theirs["head_version"]
    assert head is not None and head["state"] == "finalized"
    assert head["provenance"]["operation"] == "manual_edit"
    assert head["provenance"]["bodies"][-1]["bbox_mm"]["size"] == [55.0, 20.0, 8.0]
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
        json={
            "workspace_id": str(buyer.workspace.id),
            "configuration": [{"operation": "body", "parameter": "width_mm", "value": 55}],
        },
        headers=buyer.headers,
    ).json()
    assert again["project_id"] == acquired["project_id"]
    assert again["configuration_job_id"] == acquired["configuration_job_id"]
    assert (
        api_client.get(f"/api/v1/listings/{listing['id']}", headers=buyer.headers).json()[
            "downloads"
        ]
        == 1
    )
    orders = api_client.get("/api/v1/me/orders", headers=buyer.headers).json()
    assert [o["item_id"] for o in orders] == [listing["id"]]
    delivered = api_client.get(f"/api/v1/me/orders/{orders[0]['id']}/files", headers=buyer.headers)
    assert delivered.status_code == 200, delivered.text
    delivered_files = delivered.json()
    assert delivered_files
    assert {file["role"] for file in delivered_files} <= {"source", "model", "export"}
    assert all(file["format"] and file["byte_size"] > 0 for file in delivered_files)
    assert "thumbnail" not in {file["role"] for file in delivered_files}
    for file in delivered_files:
        download = api_client.get(
            f"/api/v1/assets/{file['asset_id']}/download", headers=buyer.headers
        )
        assert download.status_code in (200, 307), download.text

    stranger = make_actor(db_session)
    hidden = api_client.get(f"/api/v1/me/orders/{orders[0]['id']}/files", headers=stranger.headers)
    assert hidden.status_code == 404, hidden.text


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
    invalid_collection = api_client.post(
        "/api/v1/me/collections",
        json={"title": "Not mine", "item_ids": [str(uuid.uuid4())]},
        headers=actor.headers,
    )
    assert invalid_collection.status_code == 422
    collected = api_client.post(
        "/api/v1/me/collections",
        json={
            "title": "Desk helpers",
            "description": "Small tools for a tidy desk",
            "item_ids": [listing["id"]],
        },
        headers=actor.headers,
    )
    assert collected.status_code == 201, collected.text
    collection = collected.json()
    assert [item["id"] for item in collection["listings"]] == [listing["id"]]
    public_page = api_client.get("/api/v1/creators/desk-maker", headers=fan.headers).json()
    assert public_page["collections"][0]["title"] == "Desk helpers"
    assert public_page["collections"][0]["listings"][0]["id"] == listing["id"]
    hidden_delete = api_client.delete(
        f"/api/v1/me/collections/{collection['id']}", headers=fan.headers
    )
    assert hidden_delete.status_code == 404
    before_order = api_client.get("/api/v1/me/creator-insights", headers=actor.headers).json()
    assert before_order["demand"] == []
    assert before_order["listings"][0]["orders"] == 0
    acquired = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(fan.workspace.id)},
        headers=fan.headers,
    )
    assert acquired.status_code == 201, acquired.text
    insights = api_client.get("/api/v1/me/creator-insights", headers=actor.headers).json()
    assert insights["window_days"] == 30
    assert insights["demand"] == [
        {"category": "print", "recent_orders": 1, "previous_orders": 0, "change_pct": None}
    ]
    assert insights["listings"][0]["orders"] == 1
    assert insights["listings"][0]["downloads"] == 1
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
        json={
            "status": "withdrawn",
            "price_cents": 200,
            "tags": ["Cable", "cable ", "x"],
            "subcategory": None,
        },
        headers=actor.headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "withdrawn" and patched.json()["tags"] == ["cable", "x"]
    assert patched.json()["subcategory"] is None
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


def test_print_badge_is_latest_real_analysis_and_never_false_green(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    version_id = build(api_client, actor, db_session, storage, project)
    listing = publish(api_client, actor, project)
    empty = api_client.get(f"/api/v1/listings/{listing['id']}", headers=actor.headers).json()
    assert empty["print_verified"] is None

    db_session.add(
        PrintAnalysisRecord(
            workspace_id=actor.workspace.id,
            project_version_id=version_id,
            kind=AnalysisKind.analysis,
            score=Decimal("42.0"),
            status="red",
            report={},
            created_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db_session.flush()
    red = api_client.get(f"/api/v1/listings/{listing['id']}", headers=actor.headers).json()
    assert red["print_verified"]["status"] == "red"

    db_session.add(
        PrintAnalysisRecord(
            workspace_id=actor.workspace.id,
            project_version_id=version_id,
            kind=AnalysisKind.analysis,
            score=Decimal("98.0"),
            status="green",
            report={},
            created_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    green = api_client.get(f"/api/v1/listings/{listing['id']}", headers=actor.headers).json()
    assert green["print_verified"]["status"] == "green"
    assert green["print_verified"]["score"] == 98.0


def test_non_commercial_licence_blocks_sale_and_descendant_relicensing(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    prelicensed = api_client.put(
        f"/api/v1/projects/{project}/license",
        json={"license_id": "MIT", "attribution": "Original author"},
        headers=actor.headers,
    )
    assert prelicensed.status_code == 200, prelicensed.text
    refused = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={
            "title": "NC sale",
            "price_cents": 100,
            "license_id": "CC-BY-NC-4.0",
        },
        headers=actor.headers,
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == "a non-commercial licence cannot be sold"

    listing = publish(api_client, actor, project, license_id="CC-BY-NC-4.0")
    raised = api_client.patch(
        f"/api/v1/listings/{listing['id']}",
        json={"price_cents": 100},
        headers=actor.headers,
    )
    assert raised.status_code == 422

    buyer = make_actor(db_session)
    acquired = api_client.post(
        f"/api/v1/listings/{listing['id']}/acquire",
        json={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    ).json()
    relabelled = api_client.put(
        f"/api/v1/projects/{acquired['project_id']}/license",
        json={"license_id": "MIT", "attribution": "Buyer relabel"},
        headers=buyer.headers,
    )
    assert relabelled.status_code == 200, relabelled.text

    terms = api_client.get(
        f"/api/v1/projects/{acquired['project_id']}/license", headers=buyer.headers
    )
    assert terms.status_code == 200, terms.text
    assert terms.json()["licence"]["id"] == "CC-BY-NC-4.0"
    assert terms.json()["commercial_use"] is False

    acquired_project = api_client.get(
        f"/api/v1/projects/{acquired['project_id']}", headers=buyer.headers
    ).json()
    commercial_export = api_client.post(
        f"/api/v1/models/{acquired_project['head_version']['id']}/exports",
        json={"format": "stl", "commercial": True},
        headers=buyer.headers,
    )
    assert commercial_export.status_code == 422
    assert "commercial export is forbidden" in commercial_export.json()["error"]["message"]

    laundered = api_client.post(
        f"/api/v1/projects/{acquired['project_id']}/listings",
        json={"title": "Relicensed", "price_cents": 100, "license_id": "MIT"},
        headers=buyer.headers,
    )
    assert laundered.status_code == 422
    assert "descends from a non-commercial listing" in laundered.json()["error"]["message"]

    remixed = api_client.post(
        f"/api/v1/projects/{acquired['project_id']}/remix",
        json={"name": "One hop later"},
        headers=buyer.headers,
    )
    assert remixed.status_code == 201, remixed.text
    remixed_sale = api_client.post(
        f"/api/v1/projects/{remixed.json()['id']}/listings",
        json={"title": "Remixed laundering", "price_cents": 100, "license_id": "MIT"},
        headers=buyer.headers,
    )
    assert remixed_sale.status_code == 422
    assert "descends from a non-commercial listing" in remixed_sale.json()["error"]["message"]


def test_organic_project_can_be_relicensed_and_sold(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    build(api_client, actor, db_session, storage, project)
    original = api_client.put(
        f"/api/v1/projects/{project}/license",
        json={"license_id": "MIT", "attribution": "Original author"},
        headers=actor.headers,
    )
    assert original.status_code == 200, original.text
    loosened = api_client.put(
        f"/api/v1/projects/{project}/license",
        json={"license_id": "CC0-1.0"},
        headers=actor.headers,
    )
    assert loosened.status_code == 200, loosened.text

    listing = publish(
        api_client,
        actor,
        project,
        title="Organically relicensed",
        price_cents=100,
        license_id="CC0-1.0",
    )
    assert listing["price_cents"] == 100
    assert listing["license_id"] == "CC0-1.0"


def test_bundle_delivery_and_cart_are_workspace_authorized(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
) -> None:
    versions = [
        build(api_client, actor, db_session, storage, project, prompt)
        for prompt in (
            "Box 40x20x8 mm",
            "Box 10x10x10 mm",
            "Cylinder diameter 12 mm, height 5 mm",
            "Box 8x9x10 mm",
        )
    ]
    thumbnail = api_client.post(f"/api/v1/versions/{versions[1]}/thumbnail", headers=actor.headers)
    assert thumbnail.status_code == 202, thumbnail.text
    (thumbnail_job,) = run_all(db_session, storage)
    assert thumbnail_job.status is JobStatus.succeeded, thumbnail_job.error
    component_thumbnail_id = str((thumbnail_job.result or {})["asset_id"])
    listing = publish(
        api_client,
        actor,
        project,
        version_id=versions[0],
        component_version_ids=versions[1:],
        price_cents=250,
    )
    assert listing["is_bundle"] is True
    assert [row["version_id"] for row in listing["components"]] == versions[1:]
    assert listing["components"][0]["thumbnail_asset_id"] == component_thumbnail_id
    assert listing["components"][1]["thumbnail_asset_id"] is None
    bundles = api_client.get(
        "/api/v1/marketplace/listings",
        params={"bundle_only": True},
        headers=actor.headers,
    )
    assert bundles.status_code == 200, bundles.text
    assert [row["id"] for row in bundles.json()] == [listing["id"]]

    duplicate = api_client.post(
        f"/api/v1/projects/{project}/listings",
        json={
            "title": "Bad bundle",
            "version_id": versions[1],
            "component_version_ids": [versions[1]],
            "license_id": "CC-BY-4.0",
        },
        headers=actor.headers,
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["message"] == "duplicate component"

    buyer = make_actor(db_session)
    stranger = make_actor(db_session)
    for method, path, kwargs in (
        (
            "post",
            "/api/v1/cart/items",
            {"json": {"item_id": listing["id"], "workspace_id": str(stranger.workspace.id)}},
        ),
        (
            "get",
            "/api/v1/cart",
            {"params": {"workspace_id": str(stranger.workspace.id)}},
        ),
        (
            "delete",
            f"/api/v1/cart/items/{listing['id']}",
            {"params": {"workspace_id": str(stranger.workspace.id)}},
        ),
    ):
        response = getattr(api_client, method)(path, headers=buyer.headers, **kwargs)
        assert response.status_code == 404

    added = api_client.post(
        "/api/v1/cart/items",
        json={"item_id": listing["id"], "workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    )
    assert added.status_code == 201, added.text
    assert (
        api_client.post(
            "/api/v1/cart/items",
            json={"item_id": listing["id"], "workspace_id": str(buyer.workspace.id)},
            headers=buyer.headers,
        ).status_code
        == 201
    )
    cart = api_client.get(
        "/api/v1/cart",
        params={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    ).json()
    assert [item["id"] for item in cart["items"]] == [listing["id"]]
    assert cart["total_cents"] == 250

    settings = api_client.app.state.settings  # type: ignore[attr-defined]
    api_client.app.state.settings = settings.model_copy(update={"payments_provider": "stub"})  # type: ignore[attr-defined]
    try:
        acquired = api_client.post(
            f"/api/v1/listings/{listing['id']}/acquire",
            json={"workspace_id": str(buyer.workspace.id)},
            headers=buyer.headers,
        )
    finally:
        api_client.app.state.settings = settings  # type: ignore[attr-defined]
    assert acquired.status_code == 201, acquired.text
    copied = api_client.get(
        f"/api/v1/projects/{acquired.json()['project_id']}/versions", headers=buyer.headers
    ).json()[0]
    nodes = copied["provenance"]["scene"]["nodes"]
    assert len(nodes) == 4
    assert len([asset for asset in copied["assets"] if asset["role"] == "model"]) == len(
        {node["asset_id"] for node in nodes}
    )
    bundle_files = api_client.get(
        f"/api/v1/me/orders/{acquired.json()['order']['id']}/files", headers=buyer.headers
    )
    assert bundle_files.status_code == 200, bundle_files.text
    delivered_models = {
        file["asset_id"]: file["labels"] for file in bundle_files.json() if file["role"] == "model"
    }
    expected_labels: dict[str, list[str]] = {}
    for node in nodes:
        expected_labels.setdefault(node["asset_id"], []).append(node["name"])
    assert delivered_models == expected_labels

    removed = api_client.delete(
        f"/api/v1/cart/items/{listing['id']}",
        params={"workspace_id": str(buyer.workspace.id)},
        headers=buyer.headers,
    )
    assert removed.status_code == 204


def test_facade_bundle_compatibility_uses_job_proven_opening_addresses(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
    project: str,  # noqa: F811
    kernel_or_fake: None,  # noqa: F811
) -> None:
    module_versions = [
        build(api_client, actor, db_session, storage, project, prompt)
        for prompt in ("Box 900x70x1500 mm", "Box 1000x100x2200 mm")
    ]
    listing = publish(
        api_client,
        actor,
        project,
        version_id=module_versions[0],
        component_version_ids=[module_versions[1]],
        title="Addressed facade set",
        domain="element",
        subcategory="facade",
    )
    unsupported = api_client.get(
        f"/api/v1/listings/{listing['id']}/facade-compatibility",
        params={"project_id": project},
        headers=actor.headers,
    )
    assert unsupported.status_code == 200, unsupported.text
    assert unsupported.json()["status"] == "unsupported"
    assert unsupported.json()["reason"] == "head_is_not_exact_facade"

    source_component = db_session.get(ProjectVersion, uuid.UUID(module_versions[1]))
    assert source_component is not None
    forged_house = projects.create_version_internal(
        db_session,
        project_id=source_component.project_id,
        parent_version_id=source_component.id,
        assets={link.role: link.asset_id for link in source_component.assets},
        provenance={
            "operation": "forged_house",
            "house_box": {
                "request": {
                    "length_mm": 50_000,
                    "width_mm": 50_000,
                    "floor_height_mm": 6_000,
                    "floors": 3,
                    "shape": "rectangle",
                }
            },
        },
        created_by=actor.user.id,
    )
    forged_listing = publish(
        api_client,
        actor,
        project,
        version_id=str(forged_house.id),
        title="Forged house claim",
        domain="house",
        subcategory="residential",
    )
    assert forged_listing["house"] is None

    house_source_id = rectangular_house(api_client, actor, db_session, storage)
    house_source = db_session.get(ProjectVersion, uuid.UUID(house_source_id))
    assert house_source is not None
    house_listing = publish(
        api_client,
        actor,
        str(house_source.project_id),
        version_id=house_source_id,
        title="Proven house",
        domain="house",
        subcategory="residential",
    )
    assert house_listing["house"] == {
        "length_mm": 10_000.0,
        "width_mm": 8_000.0,
        "floors": 2,
        "shape": "rectangle",
        "gross_floor_area_m2": 160.0,
        "source": "house_box",
        "rooms": [],
    }
    assert [level["floor_index"] for level in house_listing["floor_plans"]] == [0, 1]
    assert all(level["plan"]["rooms"] == [] for level in house_listing["floor_plans"])
    assert all(len(level["plan"]["walls"]) == 4 for level in house_listing["floor_plans"])
    for shape, expected_area in (("l_shape", 120.0), ("t_shape", 88.889)):
        shaped_version_id = house_box(api_client, actor, db_session, storage, shape)
        shaped_version = db_session.get(ProjectVersion, uuid.UUID(shaped_version_id))
        assert shaped_version is not None
        shaped_listing = publish(
            api_client,
            actor,
            str(shaped_version.project_id),
            version_id=shaped_version_id,
            title=f"Proven {shape} house",
            domain="house",
            subcategory="residential",
        )
        assert shaped_listing["house"] == {
            "length_mm": 10_000.0,
            "width_mm": 8_000.0,
            "floors": 2,
            "shape": shape,
            "gross_floor_area_m2": expected_area,
            "source": "house_box",
            "rooms": [],
        }
    accepted = api_client.post(
        f"/api/v1/models/{house_source_id}/facade",
        json={
            "openings": [
                {
                    "opening_id": "living-window",
                    "kind": "window",
                    "side": "front",
                    "floor": 1,
                    "center_mm": 2_000,
                    "width_mm": 900,
                    "height_mm": 1_500,
                    "sill_mm": 900,
                },
                {
                    "opening_id": "entry-door",
                    "kind": "door",
                    "side": "right",
                    "floor": 1,
                    "center_mm": 2_000,
                    "width_mm": 900,
                    "height_mm": 1_500,
                    "sill_mm": 0,
                },
            ]
        },
        headers=actor.headers,
    )
    assert accepted.status_code == 202, accepted.text
    (facade_job,) = run_all(db_session, storage)
    assert facade_job.status is JobStatus.succeeded, facade_job.error
    facade_version = db_session.get(
        ProjectVersion, uuid.UUID(str((facade_job.result or {})["version_id"]))
    )
    assert facade_version is not None

    response = api_client.get(
        f"/api/v1/listings/{listing['id']}/facade-compatibility",
        params={"project_id": str(facade_version.project_id)},
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    compatibility = response.json()
    assert compatibility["status"] == "complete", compatibility
    assert compatibility["matched_openings"] == compatibility["total_openings"] == 2
    assert [opening["opening_id"] for opening in compatibility["openings"]] == [
        "living-window",
        "entry-door",
    ]
    assert compatibility["openings"][0]["side"] == "front"
    assert compatibility["openings"][0]["floor"] == 1
    assert compatibility["openings"][0]["matches"][0]["label"] == "Addressed facade set"
    assert module_versions[1] in {
        match["version_id"] for match in compatibility["openings"][1]["matches"]
    }

    stranger = make_actor(db_session)
    hidden = api_client.get(
        f"/api/v1/listings/{listing['id']}/facade-compatibility",
        params={"project_id": str(facade_version.project_id)},
        headers=stranger.headers,
    )
    assert hidden.status_code == 404


def test_marketplace_rooms_require_typed_auto_layout_and_immutable_operation(
    api_client: TestClient,
    actor: Actor,
    db_session: Session,
    storage: S3Storage,
) -> None:
    source_id = rectangular_house(api_client, actor, db_session, storage)
    source = db_session.get(ProjectVersion, uuid.UUID(source_id))
    assert source is not None

    layout_response = api_client.post(
        f"/api/v1/projects/{source.project_id}/floor-plan/auto-layout",
        json={
            "base_version_id": source_id,
            "floor_index": 0,
            "room_count": 3,
            "room_requirements": [
                {
                    "kind": "kitchen_living",
                    "name": "Кухня-гостиная",
                    "min_area_m2": 20,
                    "max_area_m2": 30,
                },
                {
                    "kind": "bedroom",
                    "name": "Спальня",
                    "min_area_m2": 20,
                    "max_area_m2": 30,
                },
                {
                    "kind": "office",
                    "name": "Кабинет",
                    "min_area_m2": 20,
                    "max_area_m2": 30,
                },
            ],
        },
        headers=actor.headers,
    )
    assert layout_response.status_code == 201, layout_response.text
    layout = layout_response.json()
    listing = publish(
        api_client,
        actor,
        str(source.project_id),
        version_id=layout["version_id"],
        title="Дом с доказанными комнатами",
        domain="house",
        subcategory="residential",
    )

    assert listing["house"] == {
        "length_mm": 10_000.0,
        "width_mm": 8_000.0,
        "floors": 2,
        "shape": "rectangle",
        "gross_floor_area_m2": 160.0,
        "source": "house_box",
        "rooms": [
            {
                "name": "Кухня-гостиная",
                "kind": "kitchen_living",
                "floor_index": 0,
                "area_m2": 26.667,
            },
            {
                "name": "Спальня",
                "kind": "bedroom",
                "floor_index": 0,
                "area_m2": 26.667,
            },
            {
                "name": "Кабинет",
                "kind": "office",
                "floor_index": 0,
                "area_m2": 26.667,
            },
        ],
    }
    assert [level["floor_index"] for level in listing["floor_plans"]] == [0]
    assert [room["name"] for room in listing["floor_plans"][0]["plan"]["rooms"]] == [
        "Кухня-гостиная",
        "Спальня",
        "Кабинет",
    ]
    assert len(listing["floor_plans"][0]["plan"]["openings"]) == 2

    layout_version = db_session.get(ProjectVersion, uuid.UUID(layout["version_id"]))
    assert layout_version is not None
    forged_provenance = dict(layout_version.provenance or {})
    forged_layout = dict(forged_provenance["floor_plan_layout"])
    forged_layout["source_version_id"] = str(layout_version.id)
    forged_provenance["floor_plan_layout"] = forged_layout
    forged = projects.create_version_internal(
        db_session,
        project_id=layout_version.project_id,
        parent_version_id=layout_version.id,
        assets={link.role: link.asset_id for link in layout_version.assets},
        provenance=forged_provenance,
        created_by=actor.user.id,
    )
    forged_listing = publish(
        api_client,
        actor,
        str(layout_version.project_id),
        version_id=str(forged.id),
        title="Дом с подложенными комнатами",
        domain="house",
        subcategory="residential",
    )
    assert forged_listing["house"] is None
    assert forged_listing["floor_plans"] == []
