"""Engineering assistant (E16, F-005): what the engineer measured and answered, per version."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class EngineeringReportRecord(UUIDPrimaryKey, CreatedAt, Base):
    """Stored result of POST /models/{version}/engineering (T-118)."""

    __tablename__ = "engineering_reports"
    __table_args__ = (
        Index("ix_engineering_reports_version_created", "project_version_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"))
    question: Mapped[str | None] = mapped_column(String(500))
    region: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
