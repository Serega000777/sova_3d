"""Marketplace (T-148/F-004), live CAD parameters (F-045), fit search (F-046), creators (F-065)."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, SettingsDep, StorageDep
from app.models.marketplace import CreatorProfile, MarketplaceItem, MarketplaceItemComponent
from app.models.printing import PrintAnalysisRecord
from app.services import licensing, marketplace

router = APIRouter(tags=["marketplace"])

Category = Literal["print", "game", "arvr", "cad", "other"]
Domain = Literal["figure", "element", "house", "yard", "printable", "other"]


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
    domain: Domain = "other"
    subcategory: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"
    )
    tags: list[str] = Field(default_factory=list, max_length=12)
    price_cents: int = Field(default=0, ge=0, le=100_000_00)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    # the project's licence when unset; a listing always has one
    license_id: str | None = Field(default=None, max_length=40)
    component_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=64)


class ListingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: Category | None = None
    domain: Domain | None = None
    subcategory: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"
    )
    tags: list[str] | None = Field(default=None, max_length=12)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_00)
    status: Literal["published", "withdrawn"] | None = None


class PrintBadgeOut(BaseModel):
    status: Literal["green", "yellow", "red"]
    score: float
    analyzed_at: datetime

    @classmethod
    def of(cls, record: PrintAnalysisRecord | None) -> "PrintBadgeOut | None":
        if record is None or record.status not in {"green", "yellow", "red"}:
            return None
        return cls(
            status=cast(Literal["green", "yellow", "red"], record.status),
            score=float(record.score),
            analyzed_at=record.created_at,
        )


class ListingComponentOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    label: str
    sort_order: int
    summary: dict[str, Any]
    model_asset_id: uuid.UUID | None = None
    thumbnail_asset_id: uuid.UUID | None = None
    print_verified: PrintBadgeOut | None = None


class ListingParameterOut(BaseModel):
    key: str
    operation: str
    parameter: str
    value: float
    min: float
    max: float
    unit: Literal["mm", "deg"]


class ListingThumbnailOut(BaseModel):
    angle: Literal["front", "iso", "top"]
    asset_id: uuid.UUID


class ListingOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    creator_handle: str
    creator_name: str
    title: str
    description: str | None
    category: str
    domain: str
    subcategory: str | None
    tags: list[str]
    price_cents: int
    currency: str
    license_id: str
    license_name: str
    commercial_use: bool
    status: str
    downloads: int
    published_at: datetime | None
    summary: dict[str, Any]
    available_formats: list[str] = Field(default_factory=list)
    # the model file of the listed version, for the card's viewer
    model_asset_id: uuid.UUID | None = None
    # Existing canonical thumbnails only. Listing reads never enqueue rendering work.
    thumbnail_asset_id: uuid.UUID | None = None
    thumbnails: list[ListingThumbnailOut] = Field(default_factory=list)
    print_verified: PrintBadgeOut | None = None
    components: list[ListingComponentOut] = Field(default_factory=list)
    is_bundle: bool = False
    parameters: list[ListingParameterOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        item: MarketplaceItem,
        profile: CreatorProfile,
        model_asset_id: uuid.UUID | None,
        thumbnail_asset_id: uuid.UUID | None,
        *,
        thumbnails: list[ListingThumbnailOut],
        print_verified: PrintBadgeOut | None,
        components: list[ListingComponentOut],
        parameters: list[ListingParameterOut],
        available_formats: list[str],
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
            domain=item.domain,
            subcategory=item.subcategory,
            tags=list(item.tags or []),
            price_cents=item.price_cents,
            currency=item.currency,
            license_id=item.license_id,
            license_name=licence.name if licence else item.license_id,
            commercial_use=licence.commercial_use if licence else True,
            status=item.status,
            downloads=item.downloads,
            published_at=item.published_at,
            summary=dict(item.summary or {}),
            available_formats=available_formats,
            model_asset_id=model_asset_id,
            thumbnail_asset_id=thumbnail_asset_id,
            thumbnails=thumbnails,
            print_verified=print_verified,
            components=components,
            is_bundle=bool(components),
            parameters=parameters,
        )


class ListingParameterValue(BaseModel):
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameter: str = Field(pattern=r"^[a-z][a-z0-9_]*_(mm|deg)$")
    value: float


class MarketplaceSubcategoryFacetOut(BaseModel):
    id: str
    label_en: str
    label_ru: str
    order: int
    count: int


class MarketplaceDomainFacetOut(BaseModel):
    id: Domain
    label_en: str
    label_ru: str
    order: int
    count: int
    subcategories: list[MarketplaceSubcategoryFacetOut]


class MarketplaceFacetsOut(BaseModel):
    domains: list[MarketplaceDomainFacetOut]


class CreatorCollectionBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class CreatorCollectionOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    listings: list[ListingOut]


class CategoryTrendOut(BaseModel):
    category: str
    recent_orders: int
    previous_orders: int
    change_pct: float | None


class ListingInsightOut(BaseModel):
    item_id: uuid.UUID
    title: str
    downloads: int
    orders: int
    gross_cents: int
    currency: str


class CreatorInsightsOut(BaseModel):
    window_days: int
    generated_at: datetime
    demand: list[CategoryTrendOut]
    listings: list[ListingInsightOut]


class AcquireBody(BaseModel):
    workspace_id: uuid.UUID
    configuration: list[ListingParameterValue] = Field(default_factory=list, max_length=16)


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
    configuration_job_id: uuid.UUID | None = None


class CartBody(BaseModel):
    item_id: uuid.UUID
    workspace_id: uuid.UUID


class CartOut(BaseModel):
    items: list[ListingOut]
    total_cents: int


def _listing_outs(db: DbDep, items: list[MarketplaceItem]) -> list[ListingOut]:
    from app.models.versioning import (
        Asset,
        AssetRole,
        ProjectVersion,
        ThumbnailAngle,
        VersionAsset,
    )
    from app.services import assets, printing

    grouped = marketplace.components_for(db, [item.id for item in items])
    component_rows = [component for rows in grouped.values() for component in rows]
    version_ids = [item.version_id for item in items] + [row.version_id for row in component_rows]
    versions = (
        {
            version.id: version
            for version in db.scalars(
                sa.select(ProjectVersion).where(ProjectVersion.id.in_(version_ids))
            ).all()
        }
        if version_ids
        else {}
    )
    analyses = printing.latest_analyses_for(db, version_ids)
    thumbnail_rows = db.execute(
        sa.select(
            VersionAsset.version_id,
            VersionAsset.asset_id,
            VersionAsset.thumbnail_angle,
        )
        .where(
            VersionAsset.version_id.in_(version_ids),
            VersionAsset.role == AssetRole.thumbnail,
        )
        .order_by(
            VersionAsset.version_id,
            VersionAsset.created_at.desc(),
        )
    ).all()
    thumbnail_ids: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    known_angles = {angle.value for angle in ThumbnailAngle}
    for version_id, asset_id, raw_angle in thumbnail_rows:
        angle = raw_angle or ThumbnailAngle.iso.value
        if angle in known_angles:
            thumbnail_ids.setdefault(version_id, {}).setdefault(angle, asset_id)
    format_rows = db.execute(
        sa.select(VersionAsset.version_id, Asset.format)
        .join(Asset, Asset.id == VersionAsset.asset_id)
        .where(
            VersionAsset.version_id.in_(version_ids),
            VersionAsset.role.in_((AssetRole.source, AssetRole.model, AssetRole.export)),
            Asset.format.is_not(None),
        )
    ).all()
    formats_by_version: dict[uuid.UUID, set[str]] = {}
    for version_id, format_id in format_rows:
        if format_id:
            formats_by_version.setdefault(version_id, set()).add(format_id.lower())

    def component_out(row: MarketplaceItemComponent) -> ListingComponentOut:
        version = versions.get(row.version_id)
        model = assets.model_asset_of(db, version) if version is not None else None
        return ListingComponentOut(
            id=row.id,
            version_id=row.version_id,
            label=row.label,
            sort_order=row.sort_order,
            summary=dict(row.summary or {}),
            model_asset_id=model.id if model else None,
            thumbnail_asset_id=thumbnail_ids.get(row.version_id, {}).get(
                ThumbnailAngle.iso.value
            ),
            print_verified=PrintBadgeOut.of(analyses.get(row.version_id)),
        )

    output: list[ListingOut] = []
    for item in items:
        profile = marketplace.ensure_profile(db, item.creator_user_id)
        version = versions.get(item.version_id)
        model = assets.model_asset_of(db, version) if version is not None else None
        output.append(
            ListingOut.of(
                item,
                profile,
                model.id if model else None,
                thumbnail_ids.get(item.version_id, {}).get(ThumbnailAngle.iso.value),
                thumbnails=[
                    ListingThumbnailOut(angle=angle, asset_id=asset_id)
                    for angle in ThumbnailAngle
                    if (asset_id := thumbnail_ids.get(item.version_id, {}).get(angle.value))
                ],
                print_verified=PrintBadgeOut.of(analyses.get(item.version_id)),
                components=[component_out(row) for row in grouped.get(item.id, [])],
                parameters=[
                    ListingParameterOut.model_validate(parameter)
                    for parameter in marketplace.configurable_parameters(db, item.version_id)
                ],
                available_formats=sorted(formats_by_version.get(item.version_id, set())),
            )
        )
    return output


def _listing_out(db: DbDep, item: MarketplaceItem) -> ListingOut:
    return _listing_outs(db, [item])[0]


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
    collections: list[CreatorCollectionOut] = Field(default_factory=list)


def _collection_outs(
    db: DbDep, collections: list[Any]
) -> list[CreatorCollectionOut]:
    return [
        CreatorCollectionOut(
            id=collection.id,
            title=collection.title,
            description=collection.description,
            listings=_listing_outs(db, marketplace.collection_items(db, collection.id)),
        )
        for collection in collections
    ]


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
        listings=_listing_outs(db, items),
        collections=_collection_outs(db, marketplace.creator_collections(db, profile.user_id)),
    )


@router.post(
    "/me/collections", status_code=status.HTTP_201_CREATED, response_model=CreatorCollectionOut
)
def create_collection(
    body: CreatorCollectionBody, db: DbDep, principal: PrincipalDep
) -> CreatorCollectionOut:
    collection = marketplace.save_collection(
        db,
        creator_user_id=principal.user_id,
        collection_id=None,
        title=body.title,
        description=body.description,
        item_ids=body.item_ids,
    )
    return _collection_outs(db, [collection])[0]


@router.put("/me/collections/{collection_id}", response_model=CreatorCollectionOut)
def update_collection(
    collection_id: uuid.UUID,
    body: CreatorCollectionBody,
    db: DbDep,
    principal: PrincipalDep,
) -> CreatorCollectionOut:
    collection = marketplace.save_collection(
        db,
        creator_user_id=principal.user_id,
        collection_id=collection_id,
        title=body.title,
        description=body.description,
        item_ids=body.item_ids,
    )
    return _collection_outs(db, [collection])[0]


@router.delete("/me/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(
    collection_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> None:
    marketplace.delete_collection(
        db, creator_user_id=principal.user_id, collection_id=collection_id
    )


@router.get("/me/creator-insights", response_model=CreatorInsightsOut)
def creator_insights(db: DbDep, principal: PrincipalDep) -> CreatorInsightsOut:
    """F-051: observed order trends and the creator's own listing performance."""
    return CreatorInsightsOut.model_validate(
        marketplace.creator_insights(db, principal.user_id)
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
    return _listing_outs(db, marketplace.feed(db, principal.user_id))


# --- listings -----------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/listings",
    status_code=status.HTTP_201_CREATED,
    response_model=ListingOut,
)
def publish_listing(
    project_id: uuid.UUID, body: ListingBody, db: DbDep, principal: PrincipalDep
) -> ListingOut:
    item = marketplace.publish_bundle(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        version_id=body.version_id,
        title=body.title,
        description=body.description,
        category=body.category,
        domain=body.domain,
        subcategory=body.subcategory,
        tags=body.tags,
        price_cents=body.price_cents,
        currency=body.currency,
        license_id=body.license_id,
        component_version_ids=body.component_version_ids,
    )
    return _listing_out(db, item)


@router.get("/projects/{project_id}/listings", response_model=list[ListingOut])
def project_listings(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    from app.services import projects

    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    return _listing_outs(db, marketplace.listings_of_project(db, project_id))


@router.get("/marketplace/listings", response_model=list[ListingOut])
def search_listings(
    db: DbDep,
    principal: PrincipalDep,
    q: str | None = Query(default=None, max_length=200),
    category: Category | None = None,
    domain: Domain | None = None,
    subcategory: str | None = Query(
        default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"
    ),
    creator: str | None = Query(default=None, max_length=32),
    free: bool = False,
    min_price_cents: int | None = Query(default=None, ge=0, le=10_000_000),
    max_price_cents: int | None = Query(default=None, ge=0, le=10_000_000),
    bundle_only: bool = False,
    format_id: str | None = Query(
        default=None,
        alias="format",
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$",
    ),
    max_width_mm: float | None = Query(default=None, gt=0, le=1_000_000),
    max_depth_mm: float | None = Query(default=None, gt=0, le=1_000_000),
    max_height_mm: float | None = Query(default=None, gt=0, le=1_000_000),
    rotate_to_fit: bool = False,
    sort: Literal["relevant", "newest", "popular", "cheapest"] = "newest",
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ListingOut]:
    items = marketplace.search(
        db,
        q=q,
        category=category,
        domain=domain,
        subcategory=subcategory,
        creator_handle=creator,
        free_only=free,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        bundle_only=bundle_only,
        format_id=format_id,
        max_width_mm=max_width_mm,
        max_depth_mm=max_depth_mm,
        max_height_mm=max_height_mm,
        rotate_to_fit=rotate_to_fit,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return _listing_outs(db, items)


@router.get("/marketplace/facets", response_model=MarketplaceFacetsOut)
def marketplace_facets(db: DbDep, principal: PrincipalDep) -> MarketplaceFacetsOut:
    del principal  # dependency intentionally enforces an authenticated catalogue session
    return MarketplaceFacetsOut(domains=marketplace.marketplace_facets(db))


@router.get("/me/listings", response_model=list[ListingOut])
def my_listings(db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    return _listing_outs(db, marketplace.my_listings(db, principal.user_id))


@router.get("/marketplace/favorites", response_model=list[ListingOut])
def favorite_listings(db: DbDep, principal: PrincipalDep) -> list[ListingOut]:
    return _listing_outs(db, marketplace.favorites(db, user_id=principal.user_id))


@router.post(
    "/marketplace/favorites/{item_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=ListingOut,
)
def add_favorite(item_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ListingOut:
    return _listing_out(
        db, marketplace.favorite_add(db, user_id=principal.user_id, item_id=item_id)
    )


@router.delete("/marketplace/favorites/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(item_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    marketplace.favorite_remove(db, user_id=principal.user_id, item_id=item_id)


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
        domain=body.domain,
        subcategory=body.subcategory,
        subcategory_set="subcategory" in body.model_fields_set,
        tags=body.tags,
        price_cents=body.price_cents,
        status=body.status,
    )
    return _listing_out(db, item)


@router.post("/cart/items", status_code=status.HTTP_201_CREATED, response_model=ListingOut)
def add_cart_item(body: CartBody, db: DbDep, principal: PrincipalDep) -> ListingOut:
    item = marketplace.cart_add(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        item_id=body.item_id,
    )
    return _listing_out(db, item)


@router.delete("/cart/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_cart_item(
    item_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> None:
    marketplace.cart_remove(
        db, user_id=principal.user_id, workspace_id=workspace_id, item_id=item_id
    )


@router.get("/cart", response_model=CartOut)
def get_cart(
    db: DbDep,
    principal: PrincipalDep,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> CartOut:
    items = marketplace.cart_list(db, user_id=principal.user_id, workspace_id=workspace_id)
    return CartOut(
        items=_listing_outs(db, items),
        total_cents=marketplace.cart_total_cents(
            db, user_id=principal.user_id, workspace_id=workspace_id
        ),
    )


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
    item = marketplace.get_listing(db, user_id=principal.user_id, item_id=item_id)
    operations = marketplace.configuration_operations(
        db,
        item=item,
        values=[value.model_dump(mode="json") for value in body.configuration],
    )
    order, project = marketplace.acquire(
        db,
        storage,
        settings,
        user_id=principal.user_id,
        item_id=item_id,
        workspace_id=body.workspace_id,
    )
    configuration_job_id = None
    if operations:
        from app.services import edits

        assert project.head_version_id is not None
        digest = hashlib.sha256(
            json.dumps(operations, sort_keys=True).encode()
        ).hexdigest()[:24]
        job = edits.enqueue_edit(
            db,
            user_id=principal.user_id,
            version_id=project.head_version_id,
            operations=operations,
            label="Marketplace configuration",
            preview=False,
            idempotency_key=f"marketplace-config:{order.id}:{digest}",
        )
        configuration_job_id = job.id
    return AcquiredOut(
        order=OrderOut.model_validate(order),
        project_id=project.id,
        configuration_job_id=configuration_job_id,
    )


@router.get("/me/orders", response_model=list[OrderOut])
def my_orders(db: DbDep, principal: PrincipalDep) -> list[OrderOut]:
    return [
        OrderOut.model_validate(order) for order in marketplace.my_orders(db, principal.user_id)
    ]
