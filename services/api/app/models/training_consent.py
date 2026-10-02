"""Training consent (self-learning plan, step 1): a project-level opt-in, off by default.

No training pipeline consumes this yet (see docs/SELF_LEARNING_PLAN.md) — the flag only
exists so a future dataset export (plan step 3) can filter to projects whose owner opted in,
and exclude anything as soon as consent is revoked.

Two tables, not one boolean column: `ProjectTrainingConsent` is the current state a query can
join against cheaply; `ProjectTrainingConsentEvent` is the append-only history of who granted
or revoked it and when, so "when did we have permission for this data" is answerable later.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt


class ConsentAction(enum.StrEnum):
    granted = "granted"
    revoked = "revoked"


class ProjectTrainingConsent(Base):
    __tablename__ = "project_training_consent"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProjectTrainingConsentEvent(CreatedAt, Base):
    __tablename__ = "project_training_consent_events"
    __table_args__ = (
        Index("ix_training_consent_events_project_created", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[ConsentAction] = mapped_column(
        Enum(ConsentAction, name="training_consent_action"), nullable=False
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
