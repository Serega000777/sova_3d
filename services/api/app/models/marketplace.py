"""Marketplace (E29, F-004) and creators (F-065): listings, profiles, follows, collections.

A listing is a finalized version offered under a licence; acquiring it copies that version
(assets and parametric history) into the buyer's workspace with the credit written, so the
provenance graph the pack asks for runs through ordinary projects. Payments are an adapter:
what a listing costs is recorded here, how it is paid is not.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class ListingCategory(enum.StrEnum):
    print = "print"
    game = "game"
    arvr = "arvr"
    cad = "cad"
    other = "other"


class ListingStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    withdrawn = "withdrawn"
    blocked = "blocked"  # moderation: hidden from everyone but the creator


class OrderStatus(enum.StrEnum):
    completed = "completed"
    pending_payment = "pending_payment"


class CreatorProfile(Timestamps, Base):
    """Who a creator is on the marketplace: a handle for URLs, a name, a few words."""

    __tablename__ = "creator_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    handle: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))


class MarketplaceItem(UUIDPrimaryKey, Timestamps, Base):
    """A version offered on the marketplace — the pack's `marketplace_items` listing shell."""

    __tablename__ = "marketplace_items"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_marketplace_items_version_id"),
        Index("ix_marketplace_items_status_published", "status", "published_at"),
        Index("ix_marketplace_items_creator", "creator_user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    license_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # what the version looked like when it was listed: size, volume, bodies — for the card
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MarketplaceItemComponent(UUIDPrimaryKey, Base):
    """One additional finalized version delivered with a marketplace listing."""

    __tablename__ = "marketplace_item_components"
    __table_args__ = (
        UniqueConstraint("item_id", "sort_order", name="uq_marketplace_item_components_order"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_items.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MarketplaceCartItem(Base):
    """A user's pending listing for one explicit destination workspace."""

    __tablename__ = "marketplace_cart_items"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_items.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketplaceOrder(UUIDPrimaryKey, CreatedAt, Base):
    """One acquisition: who took which listing into which workspace, and how it was paid."""

    __tablename__ = "marketplace_orders"
    __table_args__ = (
        UniqueConstraint("item_id", "workspace_id", name="uq_marketplace_orders_item_workspace"),
        Index("ix_marketplace_orders_buyer", "buyer_user_id", "created_at"),
        Index("ix_marketplace_orders_project", "project_id"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_items.id", ondelete="CASCADE"), nullable=False
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    payment_provider: Mapped[str | None] = mapped_column(String(32))
    payment_reference: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")


class CreatorSubscription(CreatedAt, Base):
    """F-065: a user following a creator — their new listings make up the feed."""

    __tablename__ = "creator_subscriptions"

    follower_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class CreatorCollection(UUIDPrimaryKey, Timestamps, Base):
    """A creator-curated public group of their own marketplace listings (F-065)."""

    __tablename__ = "creator_collections"
    __table_args__ = (Index("ix_creator_collections_creator", "creator_user_id", "created_at"),)

    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class CreatorCollectionItem(Base):
    """One explicitly ordered listing inside a creator collection."""

    __tablename__ = "creator_collection_items"
    __table_args__ = (
        UniqueConstraint("collection_id", "sort_order", name="uq_creator_collection_items_order"),
    )

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("creator_collections.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_items.id", ondelete="CASCADE"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
