"""Persist revision-guarded assembly guide checklist progress.

Revision ID: 0053
Revises: 0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assembly_guide_progress",
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("guide_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "completed_step_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("revision >= 1", name="assembly_guide_progress_revision_positive"),
        sa.CheckConstraint(
            "guide_kind IN ('hinged_lid', 'sliding_lid')",
            name="assembly_guide_progress_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("assembly_guide_progress")
