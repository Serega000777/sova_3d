"""ai_requests conversation columns, workspace AI budget, executed status (T-042/T-045/T-047)

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres enums can only grow; ADD VALUE cannot run inside a transaction on older
    # servers, so it is committed on its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ai_request_status ADD VALUE IF NOT EXISTS 'executed'")

    op.add_column(
        "ai_requests",
        sa.Column(
            "clarifications",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "ai_requests",
        sa.Column(
            "conversation",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "ai_requests",
        sa.Column(
            "plan_errors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "ai_requests",
        sa.Column(
            "result_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="SET NULL",
                name="fk_ai_requests_result_version_id_project_versions",
            ),
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("ai_monthly_budget_usd", sa.Numeric(12, 2)),
    )
    op.create_check_constraint(
        "ck_workspaces_ai_budget_positive",
        "workspaces",
        "ai_monthly_budget_usd IS NULL OR ai_monthly_budget_usd > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspaces_ai_budget_positive", "workspaces", type_="check")
    op.drop_column("workspaces", "ai_monthly_budget_usd")
    op.drop_column("ai_requests", "result_version_id")
    op.drop_column("ai_requests", "plan_errors")
    op.drop_column("ai_requests", "conversation")
    op.drop_column("ai_requests", "clarifications")
    # Enum values cannot be removed in place; rebuild the type without 'executed'.
    op.execute("UPDATE ai_requests SET status = 'planned' WHERE status = 'executed'")
    op.execute("ALTER TYPE ai_request_status RENAME TO ai_request_status_old")
    op.execute(
        "CREATE TYPE ai_request_status AS ENUM "
        "('planning', 'planned', 'needs_clarification', 'rejected', 'failed')"
    )
    op.execute(
        "ALTER TABLE ai_requests ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE ai_request_status USING status::text::ai_request_status, "
        "ALTER COLUMN status SET DEFAULT 'planning'"
    )
    op.execute("DROP TYPE ai_request_status_old")
