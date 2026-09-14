"""Operations, AI requests, jobs and job artifacts (T-009).

- Operation: typed, schema-versioned command appended to a project version's
  operation log. Never free-form code.
- AIRequest: user intent + context snapshot -> OperationPlan (JSONB). Stores
  provider/model/cost so regressions are attributable.
- Job: durable async execution with idempotency key, monotonic progress and a
  strict state machine (enforced by trigger in migration 0003).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.models.core import Project, User, Workspace
from app.models.versioning import Asset, ProjectVersion


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    waiting_input = "waiting_input"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


ACTIVE_JOB_STATUSES = frozenset({JobStatus.queued, JobStatus.running, JobStatus.waiting_input})
TERMINAL_JOB_STATUSES = frozenset({JobStatus.succeeded, JobStatus.failed, JobStatus.canceled})


class FailureClass(enum.StrEnum):
    retryable = "retryable"
    permanent = "permanent"


class AIRequestStatus(enum.StrEnum):
    planning = "planning"
    planned = "planned"
    needs_clarification = "needs_clarification"
    rejected = "rejected"
    failed = "failed"
    executed = "executed"


class SafetyState(enum.StrEnum):
    ok = "ok"
    flagged = "flagged"
    blocked = "blocked"


class Operation(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint(
            "project_version_id", "sequence_no", name="uq_operations_version_sequence"
        ),
        Index("ix_operations_version_sequence", "project_version_id", "sequence_no"),
        CheckConstraint("sequence_no >= 1", name="ck_operations_sequence_positive"),
        CheckConstraint("schema_version >= 1", name="ck_operations_schema_version_positive"),
    )

    project_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    entity_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="SET NULL")
    )

    project_version: Mapped[ProjectVersion] = relationship()


class AIRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        Index("ix_ai_requests_workspace_created", "workspace_id", "created_at"),
        CheckConstraint("cost_usd >= 0", name="ck_ai_requests_cost_nonnegative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    project_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Selection entity ids, units, target intent, printer/material context, client caps.
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AIRequestStatus] = mapped_column(
        Enum(AIRequestStatus, name="ai_request_status"),
        nullable=False,
        server_default=AIRequestStatus.planning.value,
    )
    safety_state: Mapped[SafetyState] = mapped_column(
        Enum(SafetyState, name="safety_state"),
        nullable=False,
        server_default=SafetyState.ok.value,
    )
    output_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    # Clarification loop (T-042): open questions, answered rounds, validator errors.
    clarifications: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    conversation: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    plan_errors: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )

    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project | None] = relationship()
    user: Mapped[User | None] = relationship()


class Job(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_jobs_workspace_idempotency"),
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_workspace_created", "workspace_id", "created_at"),
        Index(
            "ix_jobs_active",
            "status",
            "created_at",
            postgresql_where=text("status IN ('queued', 'running', 'waiting_input')"),
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress_range"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
        CheckConstraint("cost_usd >= 0", name="ck_jobs_cost_nonnegative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    project_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, server_default=JobStatus.queued.value
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    stage: Mapped[str | None] = mapped_column(String(64))
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_class: Mapped[FailureClass | None] = mapped_column(
        Enum(FailureClass, name="failure_class")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship()
    artifacts: Mapped[list["JobArtifact"]] = relationship(back_populates="job")


class JobArtifact(CreatedAt, Base):
    __tablename__ = "job_artifacts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)

    job: Mapped[Job] = relationship(back_populates="artifacts")
    asset: Mapped[Asset] = relationship()
