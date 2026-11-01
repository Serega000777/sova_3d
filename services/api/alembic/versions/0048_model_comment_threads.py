"""Add one-level model comment threads and workspace-bound mentions.

Revision ID: 0048
Revises: 0047
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_comments",
        sa.Column("parent_comment_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "model_comments",
        sa.Column(
            "mentioned_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_model_comments_parent_comment_id_model_comments",
        "model_comments",
        "model_comments",
        ["parent_comment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_model_comments_parent_created",
        "model_comments",
        ["parent_comment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_comments_parent_created", table_name="model_comments")
    op.drop_constraint(
        "fk_model_comments_parent_comment_id_model_comments",
        "model_comments",
        type_="foreignkey",
    )
    op.drop_column("model_comments", "mentioned_user_ids")
    op.drop_column("model_comments", "parent_comment_id")
