"""Give every canonical thumbnail attachment a stable camera angle.

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("version_assets", sa.Column("thumbnail_angle", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_version_assets_thumbnail_angle",
        "version_assets",
        "(role::text = 'thumbnail' AND thumbnail_angle IN ('front', 'iso', 'top')) "
        "OR (role::text <> 'thumbnail' AND thumbnail_angle IS NULL) "
        "OR (role::text = 'thumbnail' AND thumbnail_angle IS NULL)",
    )
    op.create_index(
        "uq_version_assets_thumbnail_angle",
        "version_assets",
        ["version_id", "thumbnail_angle"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_version_assets_thumbnail_angle", table_name="version_assets")
    op.drop_constraint("ck_version_assets_thumbnail_angle", "version_assets", type_="check")
    op.drop_column("version_assets", "thumbnail_angle")
