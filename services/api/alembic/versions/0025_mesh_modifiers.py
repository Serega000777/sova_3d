"""Store non-destructive modifier stacks for imported and scanned meshes.

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mesh_modifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_version_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("modifier_key", sa.String(length=64), nullable=False),
        sa.Column("modifier_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("tolerance_mm", sa.Float(), server_default="0.2", nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence_no >= 1", name="ck_mesh_modifiers_sequence_positive"),
        sa.CheckConstraint("tolerance_mm > 0", name="ck_mesh_modifiers_tolerance_positive"),
        sa.ForeignKeyConstraint(
            ["project_version_id"], ["project_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_version_id", "modifier_key", name="uq_mesh_modifiers_version_key"
        ),
        sa.UniqueConstraint(
            "project_version_id", "sequence_no", name="uq_mesh_modifiers_version_sequence"
        ),
    )
    op.create_index(
        "ix_mesh_modifiers_version_sequence",
        "mesh_modifiers",
        ["project_version_id", "sequence_no"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_mesh_modifiers_version_sequence", table_name="mesh_modifiers")
    op.drop_table("mesh_modifiers")
