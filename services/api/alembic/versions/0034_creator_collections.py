"""Add public creator collections (F-065).

Revision ID: 0034
Revises: 0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creator_collections_creator",
        "creator_collections",
        ["creator_user_id", "created_at"],
    )
    op.create_table(
        "creator_collection_items",
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["creator_collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["marketplace_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "item_id"),
        sa.UniqueConstraint(
            "collection_id", "sort_order", name="uq_creator_collection_items_order"
        ),
    )


def downgrade() -> None:
    op.drop_table("creator_collection_items")
    op.drop_index("ix_creator_collections_creator", table_name="creator_collections")
    op.drop_table("creator_collections")
