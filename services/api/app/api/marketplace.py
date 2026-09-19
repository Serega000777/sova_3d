"""Marketplace (T-148, F-004) and creator profiles/subscriptions (F-065)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, SettingsDep, StorageDep
from app.models.marketplace import CreatorProfile, MarketplaceItem
from app.services import licensing, marketplace

router = APIRouter(tags=["marketplace"])

Category = Literal["print", "game", "arvr", "cad", "other"]


class CreatorProfileBody(BaseModel):
    handle: str | None = Field(default=None, min_length=3, max_length=32)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=2000)
    website: str | None = Field(default=None, max_length=500)


class CreatorProfileOut(BaseModel):
    user_id: uuid.UUID
    handle: str
    display_name: str
    bio: str | None
    website: str | None
    followers: int = 0
    listings: int = 0
    # whether the caller follows this creator
    following: bool = False

    @classmethod
    def of(
        cls, profile: CreatorProfile, *, followers: int, listings: int, following: bool
    ) -> "CreatorProfileOut":
        return cls(
            user_id=profile.user_id,
            handle=profile.handle,
            display_name=profile.display_name,
            bio=profile.bio,
            website=profile.website,
            followers=followers,
            listings=listings,
            following=following,
        )


class ListingBody(BaseModel):
    """What goes on the shelf: the project's head (or a kept version), under a licence."""

    version_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: Category = "print"
    tags: list[str] = Field(default_factory=list, max_length=12)
    price_cents: int = Field(default=0, ge=0, le=100_000_00)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    # the project's licence when unset; a listing always has one
    license_id: str | None = Field(default=None, max_length=40)


class ListingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: Category | None = None
    tags: list[str] | None = Field(default=None, max_length=12)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_00)
    status: Literal["published", "withdrawn"] | None = None


class ListingOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    creator_handle: str
    creator_name: str
    title: str
    description: str | None
    category: str
    tags: list[str]
    price_cents: int
    currency: str
    license_id: str
    license_name: str
    status: str
    downloads: int
    published_at: datetime | None
    summary: dict[str, Any]
    # the model file of the listed version, for the card's viewer
    model_asset_id: uuid.UUID | None = None

    @classmethod
    def of(
        cls, item: MarketplaceItem, profile: CreatorProfile, model_asset_id: uuid.UUID | None
    ) -> "ListingOut":
        licence = licensing.LICENCES.get(item.license_id)
        return cls(
            id=item.id,
            project_id=item.project_id,
            version_id=item.version_id,
            creator_handle=profile.handle,
            creator_name=profile.display_name,
            title=item.title,
            description=item.description,
            category=item.category,
            tags=list(item.tags or []),
            price_cents=item.price_cents,
            currency=item.currency,
            license_id=item.license_id,
            license_name=licence.name if licence else item.license_id,
            status=item.status,
            downloads=item.downloads,
            published_at=item.published_at,
            summary=dict(item.summary or {}),
            model_asset_id=model_asset_id,
        )


class AcquireBody(BaseModel):
    workspace_id: uuid.UUID


class OrderOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    project_id: uuid.UUID | None
    workspace_id: uuid.UUID
    price_cents: int
    currency: str
    status: str
    payment_provider: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AcquiredOut(BaseModel):
    order: OrderOut
    project_id: uuid.UUID


def _listing_out(db: DbDep, item: MarketplaceItem) -> ListingOut:
    from app.models.versioning import ProjectVersion
    from app.services import assets

    profile = marketplace.ensure_profile(db, item.creator_user_id)
    version = db.get(ProjectVersion, item.version_id)
    model = assets.model_asset_of(db, version) if version is not None else None
    return ListingOut.of(item, profile, model.id if model else None)


# --- creators -----------------------------------------------------------------------------


@router.get("/me/creator-profile", response_model=CreatorProfileOut)
def my_profile(db: DbDep, principal: PrincipalDep) -> CreatorProfileOut:
    profile = marketplace.ensure_profile(db, principal.user_id)
    return CreatorProfileOut.of(
        profile,
        followers=marketplace.followers_count(db, profile.user_id),
        listings=len(marketplace.my_listings(db, principal.user_id)),
        following=False,
    )


@router.put("/me/creator-profile", response_model=CreatorProfileOut)
def update_my_profile(
    body: CreatorProfileBody, db: DbDep, principal: PrincipalDep
) -> CreatorProfileOut:
    profile = marketplace.upsert_profile(
        db,
        user_id=principal.user_id,
        handle=body.handle,
        display_name=body.display_name,
        bio=body.bio,
        website=body.website,
    )
    return CreatorProfileOut.of(
        profile,
        followers=marketplace.followers_count(db, profile.user_id),
        listings=len(marketplace.my_listings(db, principal.user_id)),
        following=False,
    )


class CreatorPageOut(BaseModel):
    profile: CreatorProfileOut
    listings: list[ListingOut]


@router.get("/creators/{handle}", response_model=CreatorPageOut)
def creator_page(handle: str, db: DbDep, principal: PrincipalDep) -> CreatorPageOut:
    profile = marketplace.profile_by_handle(db, handle)
    items = marketplace.search(db, creator_handle=profile.handle, limit=100)
    return CreatorPageOut(
        profile=CreatorProfileOut.of(
            profile,
            followers=marketplace.followers_count(db, profile.user_id),
            listings=len(items),
            following=marketplace.is_following(
                db, follower_id=principal.user_id, creator_user_id=profile.user_id
            ),
        ),
        listings=[_listing_out(db, item) for item in items],
    )


@router.post("/creators/{handle}/follow", response_model=CreatorProfileOut)
def follow_creator(handle: str, db: DbDep, principal: PrincipalDep) -> CreatorProfileOut:
    profile = marketplace.follow(db, follower_id=principal.user_id, handle=handle)
    return CreatorProfileOut.of(
        profile,
        followers=marketplace.followers_count(db, profile.user_id),
        listings=len(marketplace.search(db, creator_handle=profile.handle, limit=100)),
        following=True,
    )


@router.delete("/creators/{handle}/follow", response_model=CreatorProfileOut)
def unfollow_creator(handle: str, db: DbDep, principal: PrincipalDep) -> CreatorProfileOut:
    profile = marketplace.unfollow(db, follower_id=principal.user_id, handle=handle)
    return CreatorProfileOut.of(
        profile,
        followers=marketplace.followers_count(db, profile.user_id),
        listings=len(marketplace.search(db, creator_handle=profile.handle, limit=100)),
        following=False,
    )


@router.get("/me/following", response_model=list[CreatorProfileOut])
def my_following(db: DbDep, principal: PrincipalDep) -> list[CreatorProfileOut]:
    return [
        CreatorProfileOut.of(
            profile,
            followers=marketplace.followers_count(db, profile.user_id),
            listings=len(marketplace.search(db, creator_handle=profile.handle, limit=100)),
            following=True,
        )
        for profile in marketplace.following(db, principal.user_id)
    ]


@router.get("/marketplace/feed", response_model=list[ListingOut])
def my_feed(db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    return [_listing_out(db, item) for item in marketplace.feed(db, principal.user_id)]


# --- listings -----------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/listings",
    status_code=status.HTTP_201_CREATED,
    response_model=ListingOut,
)
def publish_listing(
    project_id: uuid.UUID, body: ListingBody, db: DbDep, principal: PrincipalDep
) -> ListingOut:
    item = marketplace.publish(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        version_id=body.version_id,
        title=body.title,
        description=body.description,
        category=body.category,
        tags=body.tags,
        price_cents=body.price_cents,
        currency=body.currency,
        license_id=body.license_id,
    )
    return _listing_out(db, item)


@router.get("/projects/{project_id}/listings", response_model=list[ListingOut])
def project_listings(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    from app.services import projects

    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    return [_listing_out(db, item) for item in marketplace.listings_of_project(db, project_id)]


@router.get("/marketplace/listings", response_model=list[ListingOut])
def search_listings(
    db: DbDep,
    principal: PrincipalDep,
    q: str | None = Query(default=None, max_length=200),
    category: Category | None = None,
    creator: str | None = Query(default=None, max_length=32),
    free: bool = False,
    sort: Literal["newest", "popular", "cheapest"] = "newest",
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ListingOut]:
    items = marketplace.search(
        db,
        q=q,
        category=category,
        creator_handle=creator,
        free_only=free,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [_listing_out(db, item) for item in items]


@router.get("/me/listings", response_model=list[ListingOut])
def my_listings(db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    return [_listing_out(db, item) for item in marketplace.my_listings(db, principal.user_id)]


@router.get("/listings/{item_id}", response_model=ListingOut)
def get_listing(item_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ListingOut:
    return _listing_out(db, marketplace.get_listing(db, user_id=principal.user_id, item_id=item_id))


@router.patch("/listings/{item_id}", response_model=ListingOut)
def patch_listing(
    item_id: uuid.UUID, body: ListingPatch, db: DbDep, principal: PrincipalDep
) -> ListingOut:
    item = marketplace.update_listing(
        db,
        user_id=principal.user_id,
        item_id=item_id,
        title=body.title,
        description=body.description,
        category=body.category,
        tags=body.tags,
        price_cents=body.price_cents,
        status=body.status,
    )
    return _listing_out(db, item)


@router.post(
    "/listings/{item_id}/acquire", status_code=status.HTTP_201_CREATED, response_model=AcquiredOut
)
def acquire_listing(
    item_id: uuid.UUID,
    body: AcquireBody,
    db: DbDep,
    storage: StorageDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> AcquiredOut:
    """Take the listing into a workspace of yours: free ones at once, priced ones through the
    payment provider — a copy of the version with the credit written, as an ordinary project."""
    order, project = marketplace.acquire(
        db,
        storage,
        settings,
        user_id=principal.user_id,
        item_id=item_id,
        workspace_id=body.workspace_id,
    )
    return AcquiredOut(order=OrderOut.model_validate(order), project_id=project.id)


@router.get("/me/orders", response_model=list[OrderOut])
def my_orders(db: DbDep, principal: PrincipalDep) -> list[OrderOut]:
    return [
        OrderOut.model_validate(order) for order in marketplace.my_orders(db, principal.user_id)
    ]
