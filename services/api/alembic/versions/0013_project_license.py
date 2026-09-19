"""projects.license_id / attribution / source_url / remixed_from (T-133, F-072)

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("license_id", sa.String(40)))
    op.add_column("projects", sa.Column("attribution", sa.String(300)))
    op.add_column("projects", sa.Column("source_url", sa.String(500)))
    op.add_column(
        "projects",
        sa.Column(
            "remixed_from_project_id",
            sa.Uuid(),
            sa.ForeignKey(
                "projects.id",
                ondelete="SET NULL",
                name="fk_projects_remixed_from_project_id_projects",
            ),
        ),
    )
    op.create_index("ix_projects_remixed_from", "projects", ["remixed_from_project_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_remixed_from", table_name="projects")
    op.drop_column("projects", "remixed_from_project_id")
    op.drop_column("projects", "source_url")
    op.drop_column("projects", "attribution")
    op.drop_column("projects", "license_id")
