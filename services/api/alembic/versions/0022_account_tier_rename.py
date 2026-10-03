"""Account tier rename: "pro" (basic) becomes "free", "profi" (paid) becomes "pro".

Only the semantic values change. users.plan is a plain String(32) with no enum or CHECK
constraint (0001), so no DDL is needed besides the column default. Both renames run in ONE
UPDATE statement, so every row is evaluated against its pre-update value — a row cannot be
renamed "profi" -> "pro" and then swept up again by the "pro" -> "free" rule. Rows with any
other value are left untouched.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET plan = CASE plan WHEN 'pro' THEN 'free' WHEN 'profi' THEN 'pro' END "
            "WHERE plan IN ('pro', 'profi')"
        )
    )
    op.alter_column("users", "plan", server_default="free")


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET plan = CASE plan WHEN 'pro' THEN 'profi' WHEN 'free' THEN 'pro' END "
            "WHERE plan IN ('pro', 'free')"
        )
    )
    op.alter_column("users", "plan", server_default="pro")
