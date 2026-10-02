"""Account tier (F-account-tier): User.plan narrows to "pro" | "profi"; "free" becomes "pro".

"free" was never a reachable product tier — the column has been an unused placeholder since
0001 (T-007) — so flipping the default and backfilling the rows is simpler and safer than
treating "free" as a permanent synonym for "pro" throughout the app.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET plan = 'pro' WHERE plan = 'free'"))
    op.alter_column("users", "plan", server_default="pro")


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET plan = 'free' WHERE plan = 'pro'"))
    op.alter_column("users", "plan", server_default="free")
