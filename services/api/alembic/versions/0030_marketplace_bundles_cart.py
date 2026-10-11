"""marketplace bundle components and workspace carts

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_index(
        "ix_marketplace_orders_project", "marketplace_orders", ["project_id"], unique=False
    )
    op.create_table(
        "marketplace_item_components",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("marketplace_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("item_id", "sort_order", name="uq_marketplace_item_components_order"),
    )
    op.create_table(
        "marketplace_cart_items",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("marketplace_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("added_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("marketplace_cart_items")
    op.drop_table("marketplace_item_components")
    op.drop_index("ix_marketplace_orders_project", table_name="marketplace_orders")
