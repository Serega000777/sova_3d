"""Persist user-rate manufacturing estimates for exact print analyses.

Revision ID: 0052
Revises: 0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manufacturing_estimates",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_version_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("printer_profile_id", sa.Uuid(), nullable=True),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("material_cost", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("print_time_min", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("machine_rate_per_hour", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("printer_power_w", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("electricity_rate_per_kwh", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("postprocess_hours", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("postprocess_rate_per_hour", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("machine_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("electricity_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("postprocess_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["print_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["project_version_id"], ["project_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "fingerprint",
            name="uq_manufacturing_estimates_analysis_fingerprint",
        ),
    )
    op.create_index(
        "ix_manufacturing_estimates_analysis_created",
        "manufacturing_estimates",
        ["analysis_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manufacturing_estimates_analysis_created", table_name="manufacturing_estimates"
    )
    op.drop_table("manufacturing_estimates")
