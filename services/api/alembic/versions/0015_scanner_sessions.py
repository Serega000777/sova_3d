"""dedicated 3D scanners: scan mode `scanner`, frame kinds `pointcloud` / `mesh` (T-152, F-082)

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres 12+ accepts ADD VALUE inside a transaction as long as the new value is not
    # used in the same transaction; the migration only declares it.
    op.execute("ALTER TYPE scan_mode ADD VALUE IF NOT EXISTS 'scanner'")
    op.execute("ALTER TYPE scan_frame_kind ADD VALUE IF NOT EXISTS 'pointcloud'")
    op.execute("ALTER TYPE scan_frame_kind ADD VALUE IF NOT EXISTS 'mesh'")


def downgrade() -> None:
    # Enum values cannot be dropped in place; rows using them would have to go first.
    # The values are harmless to leave — the application simply stops producing them.
    pass
