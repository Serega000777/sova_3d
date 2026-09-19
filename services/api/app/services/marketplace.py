"""Marketplace (T-148, F-004) and creators (F-065).

Publishing puts a finalized version on the shelf under a licence. Acquiring copies that
version — assets and parametric history — into the buyer's workspace with the credit
written, so what the buyer got is an ordinary project that remembers where it came from.
Following a creator is a subscription; their new listings are the feed.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.config import Settings
from app.models.core import Project, User, WorkspaceRole
from app.models.execution import Operation
from app.models.marketplace import (
    CreatorProfile,
    CreatorSubscription,
    ListingCategory,
    ListingStatus,
    MarketplaceItem,
    MarketplaceOrder,
    OrderStatus,
)
from app.models.versioning import Asset, ProjectVersion, VersionState
from app.services import licensing, projects
from app.services.authz import require_workspace_role
from app.storage import ObjectStorage

HANDLE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
MAX_TAGS = 12
SEARCH_LIMIT = 100

# --- creators ---------------------------------------------------------------------------------


def slugify_handle(text: str) -> str:
    """A handle out of an email's local part or a display name — never empty, never long."""
    handle = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:32]
    if len(handle) < 3:
        handle = (handle + "-maker")[:32]
    return handle


def profile_of(db: Session, user_id: uuid.UUID) -> CreatorProfile | None:
    return db.get(CreatorProfile, user_id)


def profile_by_handle(db: Session, handle: str) -> CreatorProfile:
    profile = db.scalar(sa.select(CreatorProfile).where(CreatorProfile.handle == handle.lower()))
    if profile is None:
        raise NotFoundError("creator", handle)
    return profile


def ensure_profile(db: Session, user_id: uuid.UUID) -> CreatorProfile:
    """The user's creator profile, made from their account when they never wrote one."""
    profile = profile_of(db, user_id)
    if profile is not None:
        return profile
    user = db.get(User, user_id)
    assert user is not None
    base = slugify_handle(user.display_name or (user.email or "maker").split("@")[0])
    handle, n = base, 1
    while db.scalar(sa.select(CreatorProfile).where(CreatorProfile.handle == handle)) is not None:
        n += 1
        handle = f"{base[: 32 - len(str(n)) - 1]}-{n}"
    profile = CreatorProfile(
        user_id=user_id,
        handle=handle,
        display_name=(user.display_name or (user.email or "maker").split("@")[0])[:100],
    )
    db.add(profile)
    db.flush()
    return profile


def upsert_profile(
    db: Session,
    *,
    user_id: uuid.UUID,
    handle: str | None,
    display_name: str | None,
    bio: str | None,
    website: str | None,
) -> CreatorProfile:
    profile = ensure_profile(db, user_id)
    if handle is not None:
        wanted = handle.lower().strip()
        if not HANDLE.match(wanted):
            raise ValidationFailedError(
                "a handle is 3–32 lowercase letters, digits or dashes", {"handle": handle}
            )
        taken = db.scalar(
            sa.select(CreatorProfile).where(
                CreatorProfile.handle == wanted, CreatorProfile.user_id != user_id
            )
        )
        if taken is not None:
            raise ConflictError("that handle is taken", {"handle": wanted})
        profile.handle = wanted
    if display_name is not None:
        if not display_name.strip():
            raise ValidationFailedError("display_name must not be empty")
        profile.display_name = display_name.strip()[:100]
    if bio is not None:
        profile.bio = bio.strip()[:2000] or None
    if website is not None:
        profile.website = website.strip()[:500] or None
    db.flush()
    return profile


def follow(db: Session, *, follower_id: uuid.UUID, handle: str) -> CreatorProfile:
    creator = profile_by_handle(db, handle)
    if creator.user_id == follower_id:
        raise ValidationFailedError("you cannot follow yourself")
    existing = db.get(CreatorSubscription, (follower_id, creator.user_id))
    if existing is None:
        db.add(CreatorSubscription(follower_user_id=follower_id, creator_user_id=creator.user_id))
        db.flush()
    return creator


def unfollow(db: Session, *, follower_id: uuid.UUID, handle: str) -> CreatorProfile:
    creator = profile_by_handle(db, handle)
    existing = db.get(CreatorSubscription, (follower_id, creator.user_id))
    if existing is not None:
        db.delete(existing)
        db.flush()
    return creator


def is_following(db: Session, *, follower_id: uuid.UUID, creator_user_id: uuid.UUID) -> bool:
    return db.get(CreatorSubscription, (follower_id, creator_user_id)) is not None


def followers_count(db: Session, creator_user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            sa.select(sa.func.count())
            .select_from(CreatorSubscription)
            .where(CreatorSubscription.creator_user_id == creator_user_id)
        )
        or 0
    )


def following(db: Session, follower_id: uuid.UUID) -> list[CreatorProfile]:
    return list(
        db.scalars(
            sa.select(CreatorProfile)
            .join(
                CreatorSubscription, CreatorSubscription.creator_user_id == CreatorProfile.user_id
            )
            .where(CreatorSubscription.follower_user_id == follower_id)
            .order_by(CreatorProfile.handle)
        )
    )


def feed(db: Session, follower_id: uuid.UUID, *, limit: int = 50) -> list[MarketplaceItem]:
    """The newest listings of the creators the user follows."""
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(
                CreatorSubscription,
                CreatorSubscription.creator_user_id == MarketplaceItem.creator_user_id,
            )
            .where(
                CreatorSubscription.follower_user_id == follower_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(MarketplaceItem.published_at.desc(), MarketplaceItem.id)
            .limit(limit)
        )
    )


# --- listings ---------------------------------------------------------------------------------


def _clean_tags(tags: list[str] | None) -> list[str]:
    seen: list[str] = []
    for tag in tags or []:
        clean = re.sub(r"\s+", " ", tag.strip().lower())[:40]
        if clean and clean not in seen:
            seen.append(clean)
    return seen[:MAX_TAGS]


def _summary(version: ProjectVersion) -> dict[str, Any]:
    provenance = version.provenance or {}
    bodies = provenance.get("bodies") or []
    last = bodies[-1] if bodies and isinstance(bodies[-1], dict) else {}
    bbox = last.get("bbox_mm") or {}
    return {
        "size_mm": bbox.get("size") if isinstance(bbox, dict) else None,
        "volume_mm3": last.get("volume_mm3"),
        "parametric": bool(version.provenance and (version.provenance.get("plan_goal") or bodies)),
        "operation": provenance.get("operation"),
    }


def publish(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None,
    title: str,
    description: str | None,
    category: str,
    tags: list[str] | None,
    price_cents: int,
    currency: str,
    license_id: str | None,
) -> MarketplaceItem:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    chosen_version = version_id or project.head_version_id
    if chosen_version is None:
        raise ValidationFailedError("there is no model to publish yet")
    version = db.get(ProjectVersion, chosen_version)
    if version is None or version.project_id != project.id:
        raise NotFoundError("version", chosen_version)
    if version.state is not VersionState.finalized:
        raise ConflictError("only a kept (finalized) version can be listed")
    if not version.assets:
        raise ValidationFailedError("this version has no files to offer")
    if category not in ListingCategory.__members__:
        raise ValidationFailedError(
            "unknown category", {"known": list(ListingCategory.__members__)}
        )
    licence_id = license_id or project.license_id
    if not licence_id:
        raise ValidationFailedError(
            "choose a licence before listing: buyers must know what they may do",
            {"known": sorted(licensing.LICENCES)},
        )
    if licence_id not in licensing.LICENCES:
        raise ValidationFailedError(
            f"unknown licence {licence_id!r}", {"known": sorted(licensing.LICENCES)}
        )
    if price_cents < 0:
        raise ValidationFailedError("a price cannot be negative")
    existing = db.scalar(sa.select(MarketplaceItem).where(MarketplaceItem.version_id == version.id))
    if existing is not None:
        raise ConflictError("this version is already listed", {"listing_id": str(existing.id)})
    ensure_profile(db, user_id)
    if project.license_id is None:
        project.license_id = licence_id  # the project now says what it is offered under

    item = MarketplaceItem(
        workspace_id=project.workspace_id,
        project_id=project.id,
        version_id=version.id,
        creator_user_id=user_id,
        title=title.strip()[:200],
        description=(description or "").strip()[:5000] or None,
        category=category,
        tags=_clean_tags(tags),
        price_cents=price_cents,
        currency=currency.upper()[:3],
        license_id=licence_id,
        status=ListingStatus.published.value,
        published_at=datetime.now(UTC),
        summary=_summary(version),
    )
    db.add(item)
    db.flush()
    return item


def get_listing(db: Session, *, user_id: uuid.UUID, item_id: uuid.UUID) -> MarketplaceItem:
    """A published listing is public; anything else only its creator sees."""
    item = db.get(MarketplaceItem, item_id)
    if item is None:
        raise NotFoundError("listing", item_id)
    if item.status != ListingStatus.published.value and item.creator_user_id != user_id:
        raise NotFoundError("listing", item_id)
    return item


def update_listing(
    db: Session,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    price_cents: int | None = None,
    status: str | None = None,
) -> MarketplaceItem:
    item = db.get(MarketplaceItem, item_id)
    if item is None or item.creator_user_id != user_id:
        raise NotFoundError("listing", item_id)
    if title is not None:
        if not title.strip():
            raise ValidationFailedError("title must not be empty")
        item.title = title.strip()[:200]
    if description is not None:
        item.description = description.strip()[:5000] or None
    if category is not None:
        if category not in ListingCategory.__members__:
            raise ValidationFailedError("unknown category")
        item.category = category
    if tags is not None:
        item.tags = _clean_tags(tags)
    if price_cents is not None:
        if price_cents < 0:
            raise ValidationFailedError("a price cannot be negative")
        item.price_cents = price_cents
    if status is not None:
        if status not in (ListingStatus.published.value, ListingStatus.withdrawn.value):
            raise ValidationFailedError("a creator can publish or withdraw a listing")
        if item.status == ListingStatus.blocked.value:
            raise ConflictError("this listing was blocked by moderation")
        if status == ListingStatus.published.value and item.status != status:
            item.published_at = datetime.now(UTC)
        item.status = status
    db.flush()
    return item


def my_listings(db: Session, user_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .where(MarketplaceItem.creator_user_id == user_id)
            .order_by(MarketplaceItem.created_at.desc(), MarketplaceItem.id)
        )
    )


def listings_of_project(db: Session, project_id: uuid.UUID) -> list[MarketplaceItem]:
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .where(MarketplaceItem.project_id == project_id)
            .order_by(MarketplaceItem.created_at.desc())
        )
    )


def search(
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    creator_handle: str | None = None,
    free_only: bool = False,
    sort: str = "newest",
    limit: int = 30,
    offset: int = 0,
) -> list[MarketplaceItem]:
    """Published listings: by words in the title, description or tags, by category, by
    creator; newest, most taken, or cheapest first."""
    query = sa.select(MarketplaceItem).where(
        MarketplaceItem.status == ListingStatus.published.value
    )
    if q and q.strip():
        for word in q.strip().split()[:6]:
            like = f"%{word}%"
            query = query.where(
                sa.or_(
                    MarketplaceItem.title.ilike(like),
                    MarketplaceItem.description.ilike(like),
                    sa.cast(MarketplaceItem.tags, sa.Text).ilike(like),
                )
            )
    if category:
        query = query.where(MarketplaceItem.category == category)
    if creator_handle:
        creator = profile_by_handle(db, creator_handle)
        query = query.where(MarketplaceItem.creator_user_id == creator.user_id)
    if free_only:
        query = query.where(MarketplaceItem.price_cents == 0)
    if sort == "popular":
        query = query.order_by(
            MarketplaceItem.downloads.desc(), MarketplaceItem.published_at.desc()
        )
    elif sort == "cheapest":
        query = query.order_by(MarketplaceItem.price_cents, MarketplaceItem.published_at.desc())
    else:
        query = query.order_by(MarketplaceItem.published_at.desc(), MarketplaceItem.id)
    return list(db.scalars(query.limit(min(limit, SEARCH_LIMIT)).offset(offset)))


# --- acquiring ---------------------------------------------------------------------------------


def _copy_asset(
    db: Session,
    storage: ObjectStorage,
    asset: Asset,
    *,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID,
) -> Asset:
    """The same bytes in the buyer's workspace: reuse them when they are already there."""
    existing = db.scalar(
        sa.select(Asset).where(Asset.workspace_id == workspace_id, Asset.sha256 == asset.sha256)
    )
    if existing is not None:
        return existing
    extension = asset.storage_key.rsplit(".", 1)[-1] if "." in asset.storage_key else "bin"
    key = storage.object_key(workspace_id, asset.sha256, extension)
    storage.copy(asset.storage_key, key)
    copy = Asset(
        workspace_id=workspace_id,
        kind=asset.kind,
        sha256=asset.sha256,
        storage_key=key,
        mime=asset.mime,
        format=asset.format,
        byte_size=asset.byte_size,
        units=asset.units,
        metadata_={**(asset.metadata_ or {}), "copied_from_asset_id": str(asset.id)},
        created_by=created_by,
    )
    db.add(copy)
    db.flush()
    return copy


def acquire(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[MarketplaceOrder, Project]:
    """Take a listing into a workspace: pay if it costs, then copy the version in."""
    from app.payments import provider_for

    item = get_listing(db, user_id=user_id, item_id=item_id)
    if item.status != ListingStatus.published.value:
        raise ConflictError("this listing is not on offer")
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    if item.workspace_id == workspace_id:
        raise ValidationFailedError("this listing already lives in that workspace")
    already = db.scalar(
        sa.select(MarketplaceOrder).where(
            MarketplaceOrder.item_id == item.id, MarketplaceOrder.workspace_id == workspace_id
        )
    )
    if already is not None and already.project_id is not None:
        project = db.get(Project, already.project_id)
        if project is not None and project.deleted_at is None:
            return already, project

    charge = None
    if item.price_cents > 0:
        charge = provider_for(settings).charge(
            amount_cents=item.price_cents, currency=item.currency, description=item.title
        )

    source = db.get(ProjectVersion, item.version_id)
    assert source is not None
    creator = ensure_profile(db, item.creator_user_id)
    licence = licensing.LICENCES[item.license_id]
    project = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        name=item.title,
        description=item.description,
    )
    project.license_id = item.license_id
    project.attribution = f"{item.title} by @{creator.handle} ({licence.name})"[:300]
    project.remixed_from_project_id = item.project_id
    db.flush()

    assets = {
        link.role: _copy_asset(
            db, storage, link.asset, workspace_id=workspace_id, created_by=user_id
        ).id
        for link in source.assets
    }
    version = projects.create_version_internal(
        db,
        project_id=project.id,
        parent_version_id=None,
        label=f"{item.title} (marketplace)",
        provenance={
            **(source.provenance or {}),
            "operation": "acquire",
            "listing_id": str(item.id),
            "source_version_id": str(source.id),
            "creator_handle": creator.handle,
            "license_id": item.license_id,
        },
        assets=assets,
        finalize=True,
        created_by=user_id,
    )
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == source.id)
        .order_by(Operation.sequence_no)
    ).all()
    for row in rows:
        db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=row.sequence_no,
                operation_type=row.operation_type,
                schema_version=row.schema_version,
                params=row.params,
                entity_refs=row.entity_refs,
                ai_request_id=None,
            )
        )
    order = already or MarketplaceOrder(
        item_id=item.id,
        buyer_user_id=user_id,
        workspace_id=workspace_id,
        price_cents=item.price_cents,
        currency=item.currency,
    )
    order.project_id = project.id
    order.status = OrderStatus.completed.value
    if charge is not None:
        order.payment_provider = charge.provider
        order.payment_reference = charge.reference
    db.add(order)
    item.downloads += 1
    db.flush()
    return order, project


def my_orders(db: Session, user_id: uuid.UUID) -> list[MarketplaceOrder]:
    return list(
        db.scalars(
            sa.select(MarketplaceOrder)
            .where(MarketplaceOrder.buyer_user_id == user_id)
            .order_by(MarketplaceOrder.created_at.desc(), MarketplaceOrder.id)
        )
    )
