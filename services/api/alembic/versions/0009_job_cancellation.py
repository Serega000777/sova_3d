"""jobs.cancel_requested + timeout_seconds for cooperative cancellation (T-095)

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A cancel is a request, not a state: the worker stops at its next checkpoint and writes
# the terminal state itself, so nothing is killed mid-write. Once asked, it stays asked.
CANCEL_GUARD = """
CREATE OR REPLACE FUNCTION jobs_cancel_request_sticky() RETURNS trigger AS $fn$
BEGIN
    IF OLD.cancel_requested AND NOT NEW.cancel_requested THEN
        RAISE EXCEPTION 'job % cancellation cannot be withdrawn', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("900")),
    )
    op.create_check_constraint(
        "ck_jobs_timeout_seconds", "jobs", "timeout_seconds BETWEEN 1 AND 86400"
    )
    op.execute(CANCEL_GUARD)
    op.execute(
        "CREATE TRIGGER jobs_cancel_request_sticky BEFORE UPDATE ON jobs "
        "FOR EACH ROW EXECUTE FUNCTION jobs_cancel_request_sticky()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS jobs_cancel_request_sticky ON jobs")
    op.execute("DROP FUNCTION IF EXISTS jobs_cancel_request_sticky()")
    op.drop_constraint("ck_jobs_timeout_seconds", "jobs", type_="check")
    op.drop_column("jobs", "timeout_seconds")
    op.drop_column("jobs", "cancel_requested")
