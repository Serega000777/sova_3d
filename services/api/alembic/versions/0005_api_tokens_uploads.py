"""api_tokens and upload_sessions (T-012 enabler)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

upload_status = postgresql.ENUM(
    "pending", "completed", "rejected", name="upload_status", create_type=False
)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_api_tokens_user_id_users"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100)),
        sa.Column("expires_at", TIMESTAMPTZ),
        sa.Column("revoked_at", TIMESTAMPTZ),
        sa.Column("last_used_at", TIMESTAMPTZ),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )

    upload_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_upload_sessions_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_upload_sessions_user_id_users"),
        ),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("format_id", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("status", upload_status, nullable=False, server_default="pending"),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(
                "assets.id", ondelete="SET NULL", name="fk_upload_sessions_asset_id_assets"
            ),
        ),
        sa.Column("rejection_reason", sa.String(255)),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_upload_sessions_workspace_idempotency"
        ),
        sa.UniqueConstraint("storage_key", name="uq_upload_sessions_storage_key"),
        sa.CheckConstraint("byte_size > 0", name="ck_upload_sessions_byte_size_positive"),
    )
    op.create_index(
        "ix_upload_sessions_workspace_created", "upload_sessions", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_workspace_created", table_name="upload_sessions")
    op.drop_table("upload_sessions")
    upload_status.drop(op.get_bind(), checkfirst=True)
    op.drop_table("api_tokens")
