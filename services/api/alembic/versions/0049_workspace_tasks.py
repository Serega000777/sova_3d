"""Add revision-guarded team workspace tasks.

Revision ID: 0049
Revises: 0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_tasks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 0", name="workspace_task_revision_nonnegative"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_tasks_workspace_completed_updated",
        "workspace_tasks",
        ["workspace_id", "completed_at", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_tasks_workspace_completed_updated", table_name="workspace_tasks")
    op.drop_table("workspace_tasks")
