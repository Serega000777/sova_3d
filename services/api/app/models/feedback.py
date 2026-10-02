"""Explicit result feedback (self-learning plan, step 2): good / bad / fixed, with a reason.

Implicit signals already exist — a rollback (T-123) or a manual edit right after an AI
request both say something about quality without the person doing anything extra. This table
is the explicit complement: a person looking at one AI or reconstruction result taps a
judgement on it. Append-only, like `AIRequest` — a result can collect more than one rating
(e.g. the owner disagrees with a collaborator) rather than overwriting the last one.
"""

import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class FeedbackRating(enum.StrEnum):
    good = "good"
    bad = "bad"
    fixed = "fixed"


class FeedbackReason(enum.StrEnum):
    """Only set when `rating == bad` (F-self-learning step 2's short reason list)."""

    prompt_mismatch = "prompt_mismatch"  # doesn't match the description
    broken_geometry = "broken_geometry"  # geometry is broken
    low_detail_quality = "low_detail_quality"  # detail quality is low
    other = "other"


class AIFeedback(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "ai_feedback"
    __table_args__ = (
        CheckConstraint(
            "ai_request_id IS NOT NULL OR job_id IS NOT NULL OR version_id IS NOT NULL",
            name="ck_ai_feedback_has_target",
        ),
        CheckConstraint(
            "reason IS NULL OR rating = 'bad'",
            name="ck_ai_feedback_reason_only_when_bad",
        ),
        Index("ix_ai_feedback_project_created", "project_id", "created_at"),
        Index("ix_ai_feedback_ai_request", "ai_request_id"),
        Index("ix_ai_feedback_job", "job_id"),
        Index("ix_ai_feedback_version", "version_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(FeedbackRating, name="feedback_rating"), nullable=False
    )
    reason: Mapped[FeedbackReason | None] = mapped_column(
        Enum(FeedbackReason, name="feedback_reason")
    )
