"""Revocable, expiring read-only links to one project (reference 62/64).

A link is a bearer secret shown once at creation; only `sha256(secret)` is stored, mirroring
`app.auth.ApiToken`. Resolving a link never grants workspace membership or any write access —
it only proves the right to view one project's current head version.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey
from app.models.core import Project, User


class ProjectShareLink(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "project_share_links"
    __table_args__ = (Index("ix_project_share_links_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    creator: Mapped[User] = relationship()
