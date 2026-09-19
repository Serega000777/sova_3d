"""fit_tests: two parts put together, and the verdict (T-130, F-027)

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "fit_tests",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id", ondelete="CASCADE", name="fk_fit_tests_workspace_id_workspaces"
            ),
            nullable=False,
        ),
        sa.Column(
            "version_a_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_fit_tests_version_a_id_project_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "version_b_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_fit_tests_version_b_id_project_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL", name="fk_fit_tests_job_id_jobs"),
        ),
        sa.Column("placement", postgresql.JSONB(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fit_tests_version_a_created", "fit_tests", ["version_a_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_fit_tests_version_a_created", table_name="fit_tests")
    op.drop_table("fit_tests")
