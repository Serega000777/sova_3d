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


class FitTestRecord(UUIDPrimaryKey, CreatedAt, Base):
    """Stored result of POST /fit-tests (T-130, F-027): part B placed against part A."""

    __tablename__ = "fit_tests"
    __table_args__ = (Index("ix_fit_tests_version_a_created", "version_a_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    version_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    version_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    placement: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
