"""Add the explicit base-tool and bounded purge-tower contract.

Revision ID: 0046
Revises: 0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "printer_profiles",
        sa.Column("base_tool", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "printer_profiles",
        sa.Column(
            "purge_tower_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "printer_profiles",
        sa.Column(
            "purge_tower_width_mm",
            sa.Numeric(precision=4, scale=1),
            server_default=sa.text("20.0"),
            nullable=False,
        ),
    )
    op.add_column(
        "printer_profiles",
        sa.Column(
            "purge_volume_mm3",
            sa.Numeric(precision=6, scale=1),
            server_default=sa.text("60.0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("printer_profiles", "purge_volume_mm3")
    op.drop_column("printer_profiles", "purge_tower_width_mm")
    op.drop_column("printer_profiles", "purge_tower_enabled")
    op.drop_column("printer_profiles", "base_tool")
