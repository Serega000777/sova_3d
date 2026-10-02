"""Plan markup (T-237b/F-087): server-side storage for pins/clouds/shapes/text/dimensions,
shared across devices and viewers instead of living only in browser localStorage.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_annotations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(200), nullable=False),
        sa.Column(
            "annotations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "plan_id", name="uq_plan_annotations_project_plan"),
    )


def downgrade() -> None:
    op.drop_table("plan_annotations")
