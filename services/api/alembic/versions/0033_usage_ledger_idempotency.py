"""Add idempotency keys for shadow job metering (F-068 phase 1).

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_ledger", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_index(
        "uq_usage_ledger_workspace_idempotency",
        "usage_ledger",
        ["workspace_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_usage_ledger_workspace_idempotency", table_name="usage_ledger")
    op.drop_column("usage_ledger", "idempotency_key")
