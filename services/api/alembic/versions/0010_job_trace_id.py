"""jobs.trace_id so a request can be followed into the work it queued (T-096)

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("trace_id", sa.String(64)))
    op.create_index("ix_jobs_trace_id", "jobs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_trace_id", table_name="jobs")
    op.drop_column("jobs", "trace_id")
