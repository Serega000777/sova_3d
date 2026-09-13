"""operations, ai_requests, jobs, job_artifacts (T-009)

Revision ID: 0003
Revises: 0002
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

job_status = postgresql.ENUM(
    "queued",
    "running",
    "waiting_input",
    "succeeded",
    "failed",
    "canceled",
    name="job_status",
    create_type=False,
)
failure_class = postgresql.ENUM("retryable", "permanent", name="failure_class", create_type=False)
ai_request_status = postgresql.ENUM(
    "planning",
    "planned",
    "needs_clarification",
    "rejected",
    "failed",
    name="ai_request_status",
    create_type=False,
)
safety_state = postgresql.ENUM("ok", "flagged", "blocked", name="safety_state", create_type=False)

TIMESTAMPTZ = sa.DateTime(timezone=True)
EMPTY_OBJECT = sa.text("'{}'::jsonb")


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, TIMESTAMPTZ, nullable=False, server_default=sa.func.now())


def _fk(
    owner: str, name: str, target: str, ondelete: str, *, nullable: bool = True
) -> sa.Column[uuid.UUID]:
    referred = target.split(".")[0]
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(target, ondelete=ondelete, name=f"fk_{owner}_{name}_{referred}"),
        nullable=nullable,
    )


# Job state machine + monotonic progress, enforced in the database.
JOBS_GUARD = """
CREATE FUNCTION jobs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  was_terminal boolean := OLD.status IN ('succeeded', 'failed', 'canceled');
  is_terminal boolean := NEW.status IN ('succeeded', 'failed', 'canceled');
BEGIN
  IF was_terminal AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'job % is terminal (%), cannot move to %', OLD.id, OLD.status, NEW.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF OLD.status = 'queued' AND NEW.status IN ('succeeded', 'waiting_input') THEN
    RAISE EXCEPTION 'job % must run before reaching %', OLD.id, NEW.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF NEW.status = OLD.status AND NEW.progress < OLD.progress THEN
    RAISE EXCEPTION 'job % progress must be monotonic (% -> %)', OLD.id, OLD.progress, NEW.progress
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF NEW.status = 'running' AND OLD.status <> 'running' THEN
    NEW.started_at := COALESCE(NEW.started_at, now());
    NEW.attempts := OLD.attempts + 1;
  END IF;
  IF is_terminal AND NOT was_terminal THEN
    NEW.finished_at := COALESCE(NEW.finished_at, now());
    IF NEW.status = 'succeeded' THEN
      NEW.progress := 100;
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER jobs_state_machine BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION jobs_guard();
"""


def upgrade() -> None:
    for enum in (job_status, failure_class, ai_request_status, safety_state):
        enum.create(op.get_bind(), checkfirst=True)

    # jobs first: ai_requests references it.
    op.create_table(
        "jobs",
        _uuid_pk(),
        _fk("jobs", "workspace_id", "workspaces.id", "RESTRICT", nullable=False),
        _fk("jobs", "project_id", "projects.id", "SET NULL"),
        _fk("jobs", "project_version_id", "project_versions.id", "SET NULL"),
        _fk("jobs", "created_by", "users.id", "SET NULL"),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("stage", sa.String(64)),
        sa.Column("input", postgresql.JSONB(), nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("failure_class", failure_class),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", TIMESTAMPTZ),
        sa.Column("finished_at", TIMESTAMPTZ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_jobs_workspace_idempotency"
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress_range"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_jobs_cost_nonnegative"),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_workspace_created", "jobs", ["workspace_id", "created_at"])
    op.create_index(
        "ix_jobs_active",
        "jobs",
        ["status", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running', 'waiting_input')"),
    )
    op.execute(JOBS_GUARD)

    op.create_table(
        "ai_requests",
        _uuid_pk(),
        _fk("ai_requests", "workspace_id", "workspaces.id", "RESTRICT", nullable=False),
        _fk("ai_requests", "project_id", "projects.id", "SET NULL"),
        _fk("ai_requests", "project_version_id", "project_versions.id", "SET NULL"),
        _fk("ai_requests", "user_id", "users.id", "SET NULL"),
        _fk("ai_requests", "job_id", "jobs.id", "SET NULL"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("status", ai_request_status, nullable=False, server_default="planning"),
        sa.Column("safety_state", safety_state, nullable=False, server_default="ok"),
        sa.Column("output_plan", postgresql.JSONB()),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        _ts("created_at"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_ai_requests_cost_nonnegative"),
    )
    op.create_index(
        "ix_ai_requests_workspace_created", "ai_requests", ["workspace_id", "created_at"]
    )

    op.create_table(
        "operations",
        _uuid_pk(),
        _fk("operations", "project_version_id", "project_versions.id", "CASCADE", nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column(
            "entity_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        _fk("operations", "ai_request_id", "ai_requests.id", "SET NULL"),
        _ts("created_at"),
        sa.UniqueConstraint(
            "project_version_id", "sequence_no", name="uq_operations_version_sequence"
        ),
        sa.CheckConstraint("sequence_no >= 1", name="ck_operations_sequence_positive"),
        sa.CheckConstraint("schema_version >= 1", name="ck_operations_schema_version_positive"),
    )
    op.create_index(
        "ix_operations_version_sequence", "operations", ["project_version_id", "sequence_no"]
    )

    op.create_table(
        "job_artifacts",
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE", name="fk_job_artifacts_job_id_jobs"),
            primary_key=True,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(
                "assets.id", ondelete="RESTRICT", name="fk_job_artifacts_asset_id_assets"
            ),
            primary_key=True,
        ),
        sa.Column("role", sa.String(32), primary_key=True),
        _ts("created_at"),
    )


def downgrade() -> None:
    op.drop_table("job_artifacts")
    op.drop_index("ix_operations_version_sequence", table_name="operations")
    op.drop_table("operations")
    op.drop_index("ix_ai_requests_workspace_created", table_name="ai_requests")
    op.drop_table("ai_requests")
    op.execute("DROP TRIGGER jobs_state_machine ON jobs")
    op.execute("DROP FUNCTION jobs_guard()")
    op.drop_index("ix_jobs_active", table_name="jobs")
    op.drop_index("ix_jobs_workspace_created", table_name="jobs")
    op.drop_index("ix_jobs_status_created", table_name="jobs")
    op.drop_table("jobs")
    for enum in (safety_state, ai_request_status, failure_class, job_status):
        enum.drop(op.get_bind(), checkfirst=True)
