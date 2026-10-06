"""Plan markup (T-237b/T-238): shared, revision-guarded annotation documents.

One row per (project, plan). ``revision`` is an optimistic-concurrency token: a stale editor
cannot replace a newer document and silently erase another participant's changes.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class PlanAnnotations(Timestamps, UUIDPrimaryKey, Base):
    __tablename__ = "plan_annotations"
    __table_args__ = (
        UniqueConstraint("project_id", "plan_id", name="uq_plan_annotations_project_plan"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(String(200), nullable=False)
    annotations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
