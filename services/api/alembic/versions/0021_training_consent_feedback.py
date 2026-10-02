"""Self-learning plan steps 1-2: project training consent (with history) and result feedback.

No training pipeline reads these tables yet (docs/SELF_LEARNING_PLAN.md) — consent exists so a
future dataset export can filter to opted-in projects, and feedback exists so AI/reconstruction
results carry an explicit quality signal alongside the implicit ones (rollback, post-AI edits).

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

training_consent_action = postgresql.ENUM(
    "granted", "revoked", name="training_consent_action", create_type=False
)
feedback_rating = postgresql.ENUM("good", "bad", "fixed", name="feedback_rating", create_type=False)
feedback_reason = postgresql.ENUM(
    "prompt_mismatch",
    "broken_geometry",
    "low_detail_quality",
    "other",
    name="feedback_reason",
    create_type=False,
)


def upgrade() -> None:
    for enum in (training_consent_action, feedback_rating, feedback_reason):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "project_training_consent",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "project_training_consent_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", training_consent_action, nullable=False),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_training_consent_events_project_created",
        "project_training_consent_events",
        ["project_id", "created_at"],
    )

    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ai_request_id", sa.Uuid(), sa.ForeignKey("ai_requests.id", ondelete="SET NULL")),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("project_versions.id", ondelete="SET NULL")
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("rating", feedback_rating, nullable=False),
        sa.Column("reason", feedback_reason),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "ai_request_id IS NOT NULL OR job_id IS NOT NULL OR version_id IS NOT NULL",
            name="ck_ai_feedback_has_target",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR rating = 'bad'",
            name="ck_ai_feedback_reason_only_when_bad",
        ),
    )
    op.create_index("ix_ai_feedback_project_created", "ai_feedback", ["project_id", "created_at"])
    op.create_index("ix_ai_feedback_ai_request", "ai_feedback", ["ai_request_id"])
    op.create_index("ix_ai_feedback_job", "ai_feedback", ["job_id"])
    op.create_index("ix_ai_feedback_version", "ai_feedback", ["version_id"])


def downgrade() -> None:
    op.drop_table("ai_feedback")
    op.drop_table("project_training_consent_events")
    op.drop_table("project_training_consent")
    for enum in (feedback_reason, feedback_rating, training_consent_action):
        enum.drop(op.get_bind(), checkfirst=True)
