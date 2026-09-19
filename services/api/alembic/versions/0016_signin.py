"""sign-in without tokens: user_identities, signin_challenges, users.phone, email optional
(T-162, F-083)

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)
PROVIDER = postgresql.ENUM("email", "phone", "yandex", "vk", name="identity_provider")


def upgrade() -> None:
    PROVIDER.create(op.get_bind(), checkfirst=True)
    provider = postgresql.ENUM(
        "email", "phone", "yandex", "vk", name="identity_provider", create_type=False
    )

    # a user who signed in by phone or through an OAuth account may have no email
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=True)
    op.add_column("users", sa.Column("phone", sa.String(32)))
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_identities_user_id_users"),
            nullable=False,
        ),
        sa.Column("provider", provider, nullable=False),
        sa.Column("subject", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200)),
        sa.Column(
            "profile", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("last_used_at", TIMESTAMPTZ),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
    )
    op.create_index("ix_user_identities_user", "user_identities", ["user_id"])

    op.create_table(
        "signin_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider", provider, nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", TIMESTAMPTZ),
        sa.Column("locale", sa.String(16), nullable=False, server_default="en"),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_signin_challenges_address_created", "signin_challenges", ["address", "created_at"]
    )

    # every existing user signed up by email: that address is their first identity
    op.execute(
        """
        INSERT INTO user_identities (user_id, provider, subject, display_name)
        SELECT id, 'email', lower(email), display_name FROM users WHERE email IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_signin_challenges_address_created", table_name="signin_challenges")
    op.drop_table("signin_challenges")
    op.drop_index("ix_user_identities_user", table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_column("users", "phone")
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=False)
    PROVIDER.drop(op.get_bind(), checkfirst=True)
