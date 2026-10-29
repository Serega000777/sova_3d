"""Add explicit generic tool-change capability to concrete printer profiles.

Revision ID: 0045
Revises: 0044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "printer_profiles",
        sa.Column(
            "tool_change_mode", sa.String(length=16), server_default="disabled", nullable=False
        ),
    )
    op.add_column(
        "printer_profiles",
        sa.Column("tool_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("printer_profiles", "tool_count")
    op.drop_column("printer_profiles", "tool_change_mode")
