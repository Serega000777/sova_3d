"""users, workspaces, workspace_members, projects (T-007)

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

workspace_kind = postgresql.ENUM("personal", "team", name="workspace_kind", create_type=False)
workspace_role = postgresql.ENUM(
    "owner", "admin", "editor", "viewer", name="workspace_role", create_type=False
)
units = postgresql.ENUM("mm", name="units", create_type=False)

UUID_PK = sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))
TIMESTAMPTZ = sa.DateTime(timezone=True)


def _created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now())


def _updated_at() -> sa.Column[datetime]:
    return sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for enum in (workspace_kind, workspace_role, units):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        UUID_PK.copy(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200)),
        sa.Column("locale", sa.String(16), nullable=False, server_default="en"),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column(
            "flags", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "workspaces",
        UUID_PK.copy(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", workspace_kind, nullable=False),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="RESTRICT", name="fk_workspaces_owner_user_id_users"
            ),
            nullable=False,
        ),
        _created_at(),
        _updated_at(),
    )

    op.create_table(
        "workspace_members",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_workspace_members_workspace_id_workspaces",
            ),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="CASCADE", name="fk_workspace_members_user_id_users"
            ),
            primary_key=True,
        ),
        sa.Column("role", workspace_role, nullable=False),
        _created_at(),
    )

    op.create_table(
        "projects",
        UUID_PK.copy(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id", ondelete="RESTRICT", name="fk_projects_workspace_id_workspaces"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("units", units, nullable=False, server_default="mm"),
        sa.Column("head_version_id", sa.Uuid()),
        sa.Column("deleted_at", TIMESTAMPTZ),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_projects_workspace_created", "projects", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_projects_workspace_created", table_name="projects")
    op.drop_table("projects")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
    for enum in (units, workspace_role, workspace_kind):
        enum.drop(op.get_bind(), checkfirst=True)
