"""marketplace: creator profiles, listings, orders, follows (T-147, F-004/F-065)

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)


def _user_fk(table: str, column: str, ondelete: str = "CASCADE") -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete=ondelete, name=f"fk_{table}_{column}_users")


def upgrade() -> None:
    op.create_table(
        "creator_profiles",
        sa.Column("user_id", sa.Uuid(), _user_fk("creator_profiles", "user_id"), primary_key=True),
        sa.Column("handle", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("bio", sa.Text()),
        sa.Column("website", sa.String(500)),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("handle", name="uq_creator_profiles_handle"),
    )

    op.create_table(
        "marketplace_items",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_marketplace_items_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey(
                "projects.id", ondelete="CASCADE", name="fk_marketplace_items_project_id_projects"
            ),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_marketplace_items_version_id_project_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "creator_user_id",
            sa.Uuid(),
            _user_fk("marketplace_items", "creator_user_id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("license_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("downloads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", TIMESTAMPTZ),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version_id", name="uq_marketplace_items_version_id"),
        sa.CheckConstraint("price_cents >= 0", name="ck_marketplace_items_price_non_negative"),
        sa.CheckConstraint(
            "category IN ('print', 'game', 'arvr', 'cad', 'other')",
            name="ck_marketplace_items_category",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn', 'blocked')",
            name="ck_marketplace_items_status",
        ),
    )
    op.create_index(
        "ix_marketplace_items_status_published",
        "marketplace_items",
        ["status", "published_at"],
    )
    op.create_index("ix_marketplace_items_creator", "marketplace_items", ["creator_user_id"])

    op.create_table(
        "marketplace_orders",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey(
                "marketplace_items.id",
                ondelete="CASCADE",
                name="fk_marketplace_orders_item_id_marketplace_items",
            ),
            nullable=False,
        ),
        sa.Column(
            "buyer_user_id",
            sa.Uuid(),
            _user_fk("marketplace_orders", "buyer_user_id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_marketplace_orders_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey(
                "projects.id", ondelete="SET NULL", name="fk_marketplace_orders_project_id_projects"
            ),
        ),
        sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("payment_provider", sa.String(32)),
        sa.Column("payment_reference", sa.String(200)),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "item_id", "workspace_id", name="uq_marketplace_orders_item_workspace"
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'pending_payment')", name="ck_marketplace_orders_status"
        ),
    )
    op.create_index(
        "ix_marketplace_orders_buyer", "marketplace_orders", ["buyer_user_id", "created_at"]
    )

    op.create_table(
        "creator_subscriptions",
        sa.Column(
            "follower_user_id",
            sa.Uuid(),
            _user_fk("creator_subscriptions", "follower_user_id"),
            primary_key=True,
        ),
        sa.Column(
            "creator_user_id",
            sa.Uuid(),
            _user_fk("creator_subscriptions", "creator_user_id"),
            primary_key=True,
        ),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "follower_user_id <> creator_user_id", name="ck_creator_subscriptions_not_self"
        ),
    )


def downgrade() -> None:
    op.drop_table("creator_subscriptions")
    op.drop_index("ix_marketplace_orders_buyer", table_name="marketplace_orders")
    op.drop_table("marketplace_orders")
    op.drop_index("ix_marketplace_items_creator", table_name="marketplace_items")
    op.drop_index("ix_marketplace_items_status_published", table_name="marketplace_items")
    op.drop_table("marketplace_items")
    op.drop_table("creator_profiles")
