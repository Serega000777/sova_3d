"""Scope mesh modifier stacks to scene nodes.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mesh_modifiers", sa.Column("scene_node_id", sa.String(length=64)))
    op.create_index(
        "ix_mesh_modifiers_version_scene_sequence",
        "mesh_modifiers",
        ["project_version_id", "scene_node_id", "sequence_no"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_mesh_modifiers_version_scene_sequence", table_name="mesh_modifiers")
    op.drop_column("mesh_modifiers", "scene_node_id")
