"""usage_ledger, append-only (T-010)

Revision ID: 0004
Revises: 0003
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

usage_kind = postgresql.ENUM(
    "ai_tokens",
    "gpu_seconds",
    "cpu_seconds",
    "storage_bytes",
    "credits",
    name="usage_kind",
    create_type=False,
)


def _fk(name: str, target: str, ondelete: str, *, nullable: bool = True) -> sa.Column[uuid.UUID]:
    referred = target.split(".")[0]
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(target, ondelete=ondelete, name=f"fk_usage_ledger_{name}_{referred}"),
        nullable=nullable,
    )


APPEND_ONLY_GUARD = """
CREATE FUNCTION usage_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'usage_ledger is append-only; post a correcting entry instead'
    USING ERRCODE = 'integrity_constraint_violation';
END $$;
CREATE TRIGGER usage_ledger_append_only BEFORE UPDATE OR DELETE ON usage_ledger
  FOR EACH ROW EXECUTE FUNCTION usage_ledger_append_only();
"""


def upgrade() -> None:
    usage_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _fk("workspace_id", "workspaces.id", "RESTRICT", nullable=False),
        _fk("user_id", "users.id", "SET NULL"),
        _fk("job_id", "jobs.id", "SET NULL"),
        _fk("ai_request_id", "ai_requests.id", "SET NULL"),
        sa.Column("kind", usage_kind, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("credits_delta", sa.Numeric(14, 4), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_ledger_quantity_nonnegative"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_usage_ledger_cost_nonnegative"),
    )
    op.create_index(
        "ix_usage_ledger_workspace_created", "usage_ledger", ["workspace_id", "created_at"]
    )
    op.execute(APPEND_ONLY_GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER usage_ledger_append_only ON usage_ledger")
    op.execute("DROP FUNCTION usage_ledger_append_only()")
    op.drop_index("ix_usage_ledger_workspace_created", table_name="usage_ledger")
    op.drop_table("usage_ledger")
    usage_kind.drop(op.get_bind(), checkfirst=True)
