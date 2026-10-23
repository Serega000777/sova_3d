"""Add marketplace domains and faceted navigation (M02/M03).

Revision ID: 0035
Revises: 0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_items",
        sa.Column("domain", sa.String(length=16), server_default="other", nullable=False),
    )
    op.add_column(
        "marketplace_items",
        sa.Column("subcategory", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_marketplace_items_status_domain",
        "marketplace_items",
        ["status", "domain", "subcategory"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketplace_items_status_domain", table_name="marketplace_items")
    op.drop_column("marketplace_items", "subcategory")
    op.drop_column("marketplace_items", "domain")
