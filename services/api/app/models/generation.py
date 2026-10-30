"""Provider-neutral records for AI 3D generation runs.

The durable ``Job`` remains the execution state machine.  This table stores the 3D-specific
request, provider attribution, estimate and artifact/quality lineage without teaching every
job type about external model providers.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps
from app.models.core import Project, Workspace
from app.models.execution import Job
from app.models.versioning import Asset


class ThreeDGeneration(Timestamps, Base):
    __tablename__ = "three_d_generations"
    __table_args__ = (
        Index("ix_three_d_generations_workspace_created", "workspace_id", "created_at"),
        Index("ix_three_d_generations_provider_model", "provider", "provider_model"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    target_format: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(255))
    raw_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    normalized_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    quality_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    job: Mapped[Job] = relationship()
    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project] = relationship()
    raw_asset: Mapped[Asset | None] = relationship(foreign_keys=[raw_asset_id])
    normalized_asset: Mapped[Asset | None] = relationship(foreign_keys=[normalized_asset_id])
