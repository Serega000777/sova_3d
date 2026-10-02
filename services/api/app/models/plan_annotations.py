"""Plan markup (T-237b): pins/clouds/shapes/text/dimensions, shared across devices and viewers.

One row per (project, plan) — a project can hold several plans (rooms of a building), each
with its own markup. Last write wins: there is no merge or CRDT, same as `ProjectReference`.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
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
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
