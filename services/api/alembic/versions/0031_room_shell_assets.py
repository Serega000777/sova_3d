"""Add RoomPlan empty-room shell assets.

Revision ID: 0031
Revises: 0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE asset_role ADD VALUE IF NOT EXISTS 'room_shell'")
    op.add_column("scan_sessions", sa.Column("room_shell_asset_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_scan_sessions_room_shell_asset_id_assets",
        "scan_sessions",
        "assets",
        ["room_shell_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_scan_sessions_room_shell_asset_id_assets", "scan_sessions", type_="foreignkey"
    )
    op.drop_column("scan_sessions", "room_shell_asset_id")
    # PostgreSQL enum values are intentionally retained across rollback.
