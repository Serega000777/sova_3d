"""Add the regenerable thumbnail asset role.

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE asset_role ADD VALUE IF NOT EXISTS 'thumbnail'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed in place.  The role is regenerable and safe
    # to leave declared when rolling application code back.
    pass
