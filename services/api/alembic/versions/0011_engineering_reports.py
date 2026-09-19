"""engineering_reports: what the engineer measured and answered per version (T-118, F-005)

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "engineering_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_engineering_reports_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_engineering_reports_project_version_id_project_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey(
                "jobs.id", ondelete="SET NULL", name="fk_engineering_reports_job_id_jobs"
            ),
        ),
        sa.Column(
            "material_id",
            sa.String(64),
            sa.ForeignKey(
                "materials.id",
                ondelete="SET NULL",
                name="fk_engineering_reports_material_id_materials",
            ),
        ),
        sa.Column("question", sa.String(500)),
        sa.Column("region", postgresql.JSONB()),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_engineering_reports_version_created",
        "engineering_reports",
        ["project_version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_engineering_reports_version_created", table_name="engineering_reports")
    op.drop_table("engineering_reports")
