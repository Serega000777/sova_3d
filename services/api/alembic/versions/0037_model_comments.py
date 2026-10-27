"""Add persistent point comments for immutable model versions.

Revision ID: 0037
Revises: 0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_comments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("point_mm", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')", name="ck_model_comments_model_comments_status"
        ),
    )
    op.create_index(
        "ix_model_comments_version_created", "model_comments", ["version_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_comments_version_created", table_name="model_comments")
    op.drop_table("model_comments")
