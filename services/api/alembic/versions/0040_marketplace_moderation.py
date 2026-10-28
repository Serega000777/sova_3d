"""Add marketplace moderation lifecycle and audit evidence.

Revision ID: 0040
Revises: 0039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_marketplace_items_status", "marketplace_items", type_="check")
    op.create_check_constraint(
        "ck_marketplace_items_status",
        "marketplace_items",
        "status IN ('draft', 'pending_review', 'published', 'withdrawn', 'blocked')",
    )
    op.add_column("marketplace_items", sa.Column("moderation_reason", sa.Text()))
    op.add_column("marketplace_items", sa.Column("moderated_by", sa.Uuid()))
    op.add_column("marketplace_items", sa.Column("moderated_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_marketplace_items_moderated_by_users",
        "marketplace_items",
        "users",
        ["moderated_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_marketplace_items_moderated_by_users", "marketplace_items", type_="foreignkey"
    )
    op.drop_column("marketplace_items", "moderated_at")
    op.drop_column("marketplace_items", "moderated_by")
    op.drop_column("marketplace_items", "moderation_reason")
    op.drop_constraint("ck_marketplace_items_status", "marketplace_items", type_="check")
    op.execute(
        "UPDATE marketplace_items SET status = 'withdrawn' WHERE status = 'pending_review'"
    )
    op.create_check_constraint(
        "ck_marketplace_items_status",
        "marketplace_items",
        "status IN ('draft', 'published', 'withdrawn', 'blocked')",
    )
