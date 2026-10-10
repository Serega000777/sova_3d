"""jobs.paused status + pause_requested/checkpoint for real pause/resume (T-250)

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `paused` is not terminal: a job may move queued/running/waiting_input -> paused (the
# worker honours a pause request at its next safe checkpoint, same as cancel) and then
# paused -> queued (resume re-enters the normal claim loop; the handler decides for
# itself, from `checkpoint`, how much of its earlier work it can skip redoing).
JOBS_GUARD = """
CREATE OR REPLACE FUNCTION jobs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  was_terminal boolean := OLD.status IN ('succeeded', 'failed', 'canceled');
  is_terminal boolean := NEW.status IN ('succeeded', 'failed', 'canceled');
BEGIN
  IF was_terminal AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'job % is terminal (%), cannot move to %', OLD.id, OLD.status, NEW.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF OLD.status IN ('queued', 'paused') AND NEW.status IN ('succeeded', 'waiting_input') THEN
    RAISE EXCEPTION 'job % must run before reaching %', OLD.id, NEW.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF NEW.status = 'paused' AND OLD.status NOT IN ('queued', 'running', 'waiting_input') THEN
    RAISE EXCEPTION 'job % cannot pause from %', OLD.id, OLD.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF OLD.status = 'paused' AND NEW.status = 'running' THEN
    RAISE EXCEPTION 'job % must resume through queued, not straight to running', OLD.id
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
"""


# The old guard body (pre-paused). Postgres enum values cannot be dropped, so 'paused' stays
# in job_status on downgrade; nothing in the schema references it once this migration's
# columns are gone.
OLD_JOBS_GUARD = """
CREATE OR REPLACE FUNCTION jobs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""


def upgrade() -> None:
    # Postgres enums can only grow; ADD VALUE cannot run inside the same transaction as a
    # later statement that reads it, so it gets its own autocommit block (0006 does this too).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'paused'")
        op.execute("ALTER TYPE scan_status ADD VALUE IF NOT EXISTS 'paused'")

    op.add_column(
        "jobs",
        sa.Column("pause_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("jobs", sa.Column("checkpoint", postgresql.JSONB()))
    op.execute(JOBS_GUARD)


def downgrade() -> None:
    op.drop_column("jobs", "checkpoint")
    op.drop_column("jobs", "pause_requested")
    op.execute(OLD_JOBS_GUARD)
