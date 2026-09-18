"""scan_sessions and scan_frames (T-078/T-079, F-002)

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

scan_status = postgresql.ENUM(
    "capturing",
    "uploading",
    "reconstructing",
    "ready",
    "accepted",
    "failed",
    "canceled",
    name="scan_status",
    create_type=False,
)
scan_mode = postgresql.ENUM("rgb", "rgb_depth", name="scan_mode", create_type=False)
frame_kind = postgresql.ENUM("rgb", "depth", name="scan_frame_kind", create_type=False)
TIMESTAMPTZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB

# A frame belongs to the session that was capturing it; re-pointing it would silently
# rewrite someone's scan history, and the frame count must follow its frames.
FRAME_GUARD = """
CREATE OR REPLACE FUNCTION scan_frames_immutable() RETURNS trigger AS $fn$
BEGIN
    IF NEW.scan_session_id <> OLD.scan_session_id
       OR NEW.asset_id <> OLD.asset_id
       OR NEW.sequence_no <> OLD.sequence_no
       OR NEW.kind <> OLD.kind THEN
        RAISE EXCEPTION 'scan frames are immutable except for pose/quality metadata';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

FRAME_COUNT = """
CREATE OR REPLACE FUNCTION scan_sessions_frame_count() RETURNS trigger AS $fn$
DECLARE
    session_id uuid := COALESCE(NEW.scan_session_id, OLD.scan_session_id);
BEGIN
    UPDATE scan_sessions
       SET frame_count = (SELECT count(*) FROM scan_frames WHERE scan_session_id = session_id)
     WHERE id = session_id;
    RETURN NULL;
END;
$fn$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    scan_status.create(op.get_bind(), checkfirst=True)
    scan_mode.create(op.get_bind(), checkfirst=True)
    frame_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "scan_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("status", scan_status, nullable=False, server_default="capturing"),
        sa.Column("mode", scan_mode, nullable=False, server_default="rgb"),
        sa.Column("label", sa.String(200)),
        sa.Column("capabilities", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("capture_stats", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("frame_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")
        ),
        sa.Column(
            "mesh_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "result_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("report", JSONB),
        sa.Column("scale_hint_mm", sa.Numeric(10, 3)),
        sa.Column("scale_confidence", sa.Numeric(4, 3)),
        sa.Column("error", JSONB),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_scan_sessions_workspace_idempotency"
        ),
        sa.CheckConstraint(
            "scale_confidence IS NULL OR (scale_confidence >= 0 AND scale_confidence <= 1)",
            name="ck_scan_sessions_scale_confidence",
        ),
    )
    op.create_index(
        "ix_scan_sessions_workspace_created", "scan_sessions", ["workspace_id", "created_at"]
    )
    op.create_index("ix_scan_sessions_project", "scan_sessions", ["project_id"])

    op.create_table(
        "scan_frames",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scan_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scan_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer, nullable=False),
        sa.Column("kind", frame_kind, nullable=False, server_default="rgb"),
        sa.Column("pose", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quality", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "scan_session_id", "sequence_no", "kind", name="uq_scan_frames_session_sequence_kind"
        ),
        sa.CheckConstraint("sequence_no >= 0", name="ck_scan_frames_sequence_no"),
    )
    op.create_index(
        "ix_scan_frames_session_sequence", "scan_frames", ["scan_session_id", "sequence_no"]
    )

    op.execute(FRAME_GUARD)
    op.execute(
        "CREATE TRIGGER trg_scan_frames_immutable BEFORE UPDATE ON scan_frames "
        "FOR EACH ROW EXECUTE FUNCTION scan_frames_immutable()"
    )
    op.execute(FRAME_COUNT)
    op.execute(
        "CREATE TRIGGER trg_scan_frames_count AFTER INSERT OR DELETE ON scan_frames "
        "FOR EACH ROW EXECUTE FUNCTION scan_sessions_frame_count()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_scan_frames_count ON scan_frames")
    op.execute("DROP FUNCTION IF EXISTS scan_sessions_frame_count()")
    op.execute("DROP TRIGGER IF EXISTS trg_scan_frames_immutable ON scan_frames")
    op.execute("DROP FUNCTION IF EXISTS scan_frames_immutable()")
    op.drop_index("ix_scan_frames_session_sequence", table_name="scan_frames")
    op.drop_table("scan_frames")
    op.drop_index("ix_scan_sessions_project", table_name="scan_sessions")
    op.drop_index("ix_scan_sessions_workspace_created", table_name="scan_sessions")
    op.drop_table("scan_sessions")
    frame_kind.drop(op.get_bind(), checkfirst=True)
    scan_mode.drop(op.get_bind(), checkfirst=True)
    scan_status.drop(op.get_bind(), checkfirst=True)
