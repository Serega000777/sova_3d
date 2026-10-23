"""Marketplace (T-148, F-004), creators (F-065) and physical fit search (F-046).

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
    MarketplaceCartItem,
    MarketplaceItem,
    MarketplaceItemComponent,
    MarketplaceOrder,
    OrderStatus,
)
from app.models.versioning import AssetRole, ProjectVersion, VersionState
from app.services import licensing, projects
from app.services.asset_copies import copy_asset_to_workspace
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
    return publish_bundle(
        db,
        user_id=user_id,
        project_id=project_id,
        version_id=version_id,
        title=title,
        description=description,
        category=category,
        tags=tags,
        price_cents=price_cents,
        currency=currency,
        license_id=license_id,
        component_version_ids=[],
    )


def publish_bundle(
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
    component_version_ids: list[uuid.UUID],
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
    licensing.assert_may_list_for_price(db, project, licence_id, price_cents)
    if version.id in component_version_ids or len(set(component_version_ids)) != len(
        component_version_ids
    ):
        raise ValidationFailedError("duplicate component")
    components: list[ProjectVersion] = []
    for component_id in component_version_ids:
        component = db.get(ProjectVersion, component_id)
        if component is None or component.project_id != project.id:
            raise NotFoundError("version", component_id)
        if component.state is not VersionState.finalized:
            raise ConflictError("only a kept (finalized) version can be listed")
        if not component.assets:
            raise ValidationFailedError("this version has no files to offer")
        components.append(component)
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
    for index, component in enumerate(components, start=1):
        db.add(
            MarketplaceItemComponent(
                item_id=item.id,
                version_id=component.id,
                label=(component.label or f"Component {index}")[:200],
                sort_order=index,
                summary=_summary(component),
            )
        )
    db.flush()
    return item


def components_for(
    db: Session, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MarketplaceItemComponent]]:
    grouped: dict[uuid.UUID, list[MarketplaceItemComponent]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return grouped
    rows = db.scalars(
        sa.select(MarketplaceItemComponent)
        .where(MarketplaceItemComponent.item_id.in_(item_ids))
        .order_by(MarketplaceItemComponent.item_id, MarketplaceItemComponent.sort_order)
    ).all()
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped


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
        project = db.get(Project, item.project_id)
        assert project is not None
        licensing.assert_may_list_for_price(db, project, item.license_id, price_cents)
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
    max_width_mm: float | None = None,
    max_depth_mm: float | None = None,
    max_height_mm: float | None = None,
    rotate_to_fit: bool = False,
    sort: str = "newest",
    limit: int = 30,
    offset: int = 0,
) -> list[MarketplaceItem]:
    """Published listings filtered by words and by an optional physical envelope.

    A dimensional search never guesses: listings without measured ``size_mm`` evidence are
    excluded. ``rotate_to_fit`` permits any axis permutation, but only when the caller supplied
    a complete three-dimensional envelope.
    """
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
    dimensional = any(
        value is not None for value in (max_width_mm, max_depth_mm, max_height_mm)
    )
    if not dimensional:
        return list(db.scalars(query.limit(min(limit, SEARCH_LIMIT)).offset(offset)))

    envelope = (max_width_mm, max_depth_mm, max_height_mm)
    if rotate_to_fit and any(value is None for value in envelope):
        raise ValidationFailedError(
            "rotate_to_fit requires width, depth and height",
            {"required": ["max_width_mm", "max_depth_mm", "max_height_mm"]},
        )

    def fits(item: MarketplaceItem) -> bool:
        raw = (item.summary or {}).get("size_mm")
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or any(not isinstance(value, (int, float)) or value <= 0 for value in raw)
        ):
            return False
        size = tuple(float(value) for value in raw)
        if rotate_to_fit:
            spaces = sorted(float(value) for value in envelope if value is not None)
            return all(part <= space for part, space in zip(sorted(size), spaces, strict=True))
        return all(
            space is None or part <= space for part, space in zip(size, envelope, strict=True)
        )

    # Apply pagination after the compatibility predicate so a page never contains false matches.
    matching = [item for item in db.scalars(query).all() if fits(item)]
    return matching[offset : offset + min(limit, SEARCH_LIMIT)]


# --- cart --------------------------------------------------------------------------------------


def cart_add(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> MarketplaceItem:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    item = get_listing(db, user_id=user_id, item_id=item_id)
    if item.status != ListingStatus.published.value:
        raise ConflictError("this listing is not on offer")
    if item.workspace_id == workspace_id:
        raise ValidationFailedError("this listing already lives in that workspace")
    key = (user_id, workspace_id, item_id)
    if db.get(MarketplaceCartItem, key) is None:
        db.add(
            MarketplaceCartItem(
                user_id=user_id,
                workspace_id=workspace_id,
                item_id=item_id,
            )
        )
        db.flush()
    return item


def cart_remove(
    db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    row = db.get(MarketplaceCartItem, (user_id, workspace_id, item_id))
    if row is not None:
        db.delete(row)
        db.flush()


def cart_list(db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[MarketplaceItem]:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return list(
        db.scalars(
            sa.select(MarketplaceItem)
            .join(MarketplaceCartItem, MarketplaceCartItem.item_id == MarketplaceItem.id)
            .where(
                MarketplaceCartItem.user_id == user_id,
                MarketplaceCartItem.workspace_id == workspace_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
            .order_by(MarketplaceCartItem.added_at, MarketplaceItem.id)
        )
    )


def cart_total_cents(db: Session, *, user_id: uuid.UUID, workspace_id: uuid.UUID) -> int:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    return int(
        db.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(MarketplaceItem.price_cents), 0))
            .join(MarketplaceCartItem, MarketplaceCartItem.item_id == MarketplaceItem.id)
            .where(
                MarketplaceCartItem.user_id == user_id,
                MarketplaceCartItem.workspace_id == workspace_id,
                MarketplaceItem.status == ListingStatus.published.value,
            )
        )
        or 0
    )


# --- acquiring ---------------------------------------------------------------------------------


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
    from app.services import assets as asset_services
    from app.services.scenes import IDENTITY, SCENE_SCHEMA_VERSION

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
    components = db.scalars(
        sa.select(MarketplaceItemComponent)
        .where(MarketplaceItemComponent.item_id == item.id)
        .order_by(MarketplaceItemComponent.sort_order)
    ).all()
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

    copied_assets = {
        link.role: copy_asset_to_workspace(
            db, storage, link.asset, workspace_id=workspace_id, created_by=user_id
        ).id
        for link in source.assets
    }
    provenance = {
        **(source.provenance or {}),
        "operation": "acquire",
        "listing_id": str(item.id),
        "source_version_id": str(source.id),
        "creator_handle": creator.handle,
        "license_id": item.license_id,
    }
    if not components:
        version = projects.create_version_internal(
            db,
            project_id=project.id,
            parent_version_id=None,
            label=f"{item.title} (marketplace)",
            provenance=provenance,
            assets=copied_assets,
            finalize=True,
            created_by=user_id,
        )
    else:
        anchor_model = copied_assets.get(AssetRole.model)
        if anchor_model is None:
            source_model = asset_services.model_asset_of(db, source)
            if source_model is None:
                raise ValidationFailedError("this version has no model file to offer")
            anchor_model = copy_asset_to_workspace(
                db, storage, source_model, workspace_id=workspace_id, created_by=user_id
            ).id
        members: list[tuple[str, uuid.UUID]] = [(item.title, anchor_model)]
        for component in components:
            component_version = db.get(ProjectVersion, component.version_id)
            if component_version is None:
                raise ValidationFailedError(
                    "a bundle component is unavailable", {"component_id": str(component.id)}
                )
            component_model = asset_services.model_asset_of(db, component_version)
            if component_model is None:
                raise ValidationFailedError(
                    "a bundle component has no model file",
                    {"component_id": str(component.id)},
                )
            copied = copy_asset_to_workspace(
                db, storage, component_model, workspace_id=workspace_id, created_by=user_id
            )
            members.append((component.label, copied.id))
        nodes = [
            {
                "id": "bundle_anchor" if index == 0 else f"bundle_component_{index}",
                "name": label,
                "kind": "object",
                "parent_id": None,
                "visible": True,
                "transform": [row[:] for row in IDENTITY],
                "asset_id": str(asset_id),
                "instance_of": None,
            }
            for index, (label, asset_id) in enumerate(members)
        ]
        provenance["scene"] = {"schema_version": SCENE_SCHEMA_VERSION, "nodes": nodes}
        non_model_assets: dict[AssetRole, uuid.UUID] = {
            role: asset_id
            for role, asset_id in copied_assets.items()
            if role is not AssetRole.model
        }
        version = projects.create_version_internal(
            db,
            project_id=project.id,
            parent_version_id=None,
            label=f"{item.title} (marketplace)",
            provenance=provenance,
            assets=non_model_assets,
            finalize=False,
            created_by=user_id,
        )
        for asset_id in dict.fromkeys(asset_id for _, asset_id in members):
            projects.attach_asset(db, version, asset_id, AssetRole.model, workspace_id=workspace_id)
        projects.finalize_version(db, version)
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
                enabled=row.enabled,
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
