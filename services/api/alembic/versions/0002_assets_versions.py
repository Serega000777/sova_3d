"""assets, project_versions, version_assets + immutability triggers (T-008)

Revision ID: 0002
Revises: 0001
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

asset_kind = postgresql.ENUM("original", "derived", name="asset_kind", create_type=False)
version_state = postgresql.ENUM("draft", "finalized", name="version_state", create_type=False)
asset_role = postgresql.ENUM(
    "source", "model", "preview", "export", "scan", name="asset_role", create_type=False
)
units = postgresql.ENUM("mm", name="units", create_type=False)

TIMESTAMPTZ = sa.DateTime(timezone=True)


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now())


# --- immutability guards -------------------------------------------------------------------
# Enforced in the database so no code path (API, worker, psql) can silently mutate history.

ASSETS_GUARD = """
CREATE FUNCTION assets_guard_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.sha256 IS DISTINCT FROM OLD.sha256
     OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
     OR NEW.mime IS DISTINCT FROM OLD.mime
     OR NEW.format IS DISTINCT FROM OLD.format
     OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
     OR NEW.units IS DISTINCT FROM OLD.units
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'assets are immutable; create a new asset for changed content'
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER assets_immutable BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION assets_guard_immutable();
"""

VERSIONS_GUARD = """
CREATE FUNCTION project_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.state = 'finalized' THEN
      RAISE EXCEPTION 'finalized project_version % cannot be deleted', OLD.id
        USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN OLD;
  END IF;

  IF OLD.state = 'finalized' THEN
    RAISE EXCEPTION 'finalized project_version % is immutable', OLD.id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  -- Draft: lineage is fixed at creation, only state/label/provenance may change.
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.project_id IS DISTINCT FROM OLD.project_id
     OR NEW.parent_version_id IS DISTINCT FROM OLD.parent_version_id
     OR NEW.sequence_no IS DISTINCT FROM OLD.sequence_no
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'project_version lineage fields are immutable'
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF NEW.state = 'finalized' AND NEW.finalized_at IS NULL THEN
    NEW.finalized_at := now();
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER project_versions_immutable BEFORE UPDATE OR DELETE ON project_versions
  FOR EACH ROW EXECUTE FUNCTION project_versions_guard();
"""

VERSION_ASSETS_GUARD = """
CREATE FUNCTION version_assets_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  rec version_assets%ROWTYPE;
  v_state version_state;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'version_assets rows are immutable; delete and insert instead'
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  rec := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  SELECT state INTO v_state FROM project_versions WHERE id = rec.version_id;
  IF v_state = 'finalized' AND rec.role IN ('source', 'model', 'scan') THEN
    RAISE EXCEPTION 'content assets of finalized project_version % are frozen', rec.version_id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN rec;
END $$;
CREATE TRIGGER version_assets_frozen BEFORE INSERT OR UPDATE OR DELETE ON version_assets
  FOR EACH ROW EXECUTE FUNCTION version_assets_guard();
"""


def upgrade() -> None:
    for enum in (asset_kind, version_state, asset_role):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "assets",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id", ondelete="RESTRICT", name="fk_assets_workspace_id_workspaces"
            ),
            nullable=False,
        ),
        sa.Column("kind", asset_kind, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(255), nullable=False),
        sa.Column("format", sa.String(32)),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("units", units),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_assets_created_by_users"),
        ),
        _created_at(),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_assets_workspace_sha256"),
        sa.UniqueConstraint("storage_key", name="uq_assets_storage_key"),
        sa.CheckConstraint("byte_size >= 0", name="ck_assets_byte_size_nonnegative"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_assets_sha256_hex"),
    )
    op.create_index("ix_assets_sha256", "assets", ["sha256"])

    op.create_table(
        "project_versions",
        _uuid_pk(),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey(
                "projects.id", ondelete="RESTRICT", name="fk_project_versions_project_id_projects"
            ),
            nullable=False,
        ),
        sa.Column(
            "parent_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="RESTRICT",
                name="fk_project_versions_parent_version_id_project_versions",
            ),
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("state", version_state, nullable=False, server_default="draft"),
        sa.Column("label", sa.String(200)),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_project_versions_created_by_users"
            ),
        ),
        sa.Column("finalized_at", TIMESTAMPTZ),
        _created_at(),
        sa.UniqueConstraint(
            "project_id", "sequence_no", name="uq_project_versions_project_sequence"
        ),
        sa.CheckConstraint("sequence_no >= 1", name="ck_project_versions_sequence_positive"),
        sa.CheckConstraint(
            "parent_version_id IS NULL OR parent_version_id <> id",
            name="ck_project_versions_no_self_parent",
        ),
    )
    op.create_index(
        "ix_project_versions_project_created", "project_versions", ["project_id", "created_at"]
    )

    op.create_table(
        "version_assets",
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_version_assets_version_id_project_versions",
            ),
            primary_key=True,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(
                "assets.id", ondelete="RESTRICT", name="fk_version_assets_asset_id_assets"
            ),
            primary_key=True,
        ),
        sa.Column("role", asset_role, primary_key=True),
        _created_at(),
    )

    op.create_foreign_key(
        "fk_projects_head_version_id_project_versions",
        "projects",
        "project_versions",
        ["head_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for ddl in (ASSETS_GUARD, VERSIONS_GUARD, VERSION_ASSETS_GUARD):
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TRIGGER version_assets_frozen ON version_assets")
    op.execute("DROP FUNCTION version_assets_guard()")
    op.execute("DROP TRIGGER project_versions_immutable ON project_versions")
    op.execute("DROP FUNCTION project_versions_guard()")
    op.execute("DROP TRIGGER assets_immutable ON assets")
    op.execute("DROP FUNCTION assets_guard_immutable()")

    op.drop_constraint(
        "fk_projects_head_version_id_project_versions", "projects", type_="foreignkey"
    )
    op.drop_table("version_assets")
    op.drop_index("ix_project_versions_project_created", table_name="project_versions")
    op.drop_table("project_versions")
    op.drop_index("ix_assets_sha256", table_name="assets")
    op.drop_table("assets")
    for enum in (asset_role, version_state, asset_kind):
        enum.drop(op.get_bind(), checkfirst=True)
