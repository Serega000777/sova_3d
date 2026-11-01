"""Small revision-guarded tasks for a team workspace (reference 64)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class WorkspaceTask(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspace_tasks"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="workspace_task_revision_nonnegative"),
        Index(
            "ix_workspace_tasks_workspace_completed_updated",
            "workspace_id",
            "completed_at",
            "updated_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
