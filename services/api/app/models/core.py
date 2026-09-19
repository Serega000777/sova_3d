"""Users, workspaces, membership and projects (T-007)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class WorkspaceKind(enum.StrEnum):
    personal = "personal"
    team = "team"


class WorkspaceRole(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class Units(enum.StrEnum):
    """Canonical unit inside the platform is millimetres; others only at the boundary."""

    mm = "mm"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    plan: Mapped[str] = mapped_column(String(32), nullable=False, server_default="free")
    flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    memberships: Mapped[list["WorkspaceMember"]] = relationship(back_populates="user")


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[WorkspaceKind] = mapped_column(
        Enum(WorkspaceKind, name="workspace_kind"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL means "use Settings.ai_workspace_monthly_budget_usd" (T-047).
    ai_monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace")
    projects: Mapped[list["Project"]] = relationship(back_populates="workspace")


class WorkspaceMember(CreatedAt, Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role"), nullable=False
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Project(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    units: Mapped[Units] = mapped_column(
        Enum(Units, name="units"), nullable=False, server_default=Units.mm.value
    )
    head_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL", use_alter=True)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # F-072: where the work comes from and what may be done with it (see app.licensing).
    license_id: Mapped[str | None] = mapped_column(String(40))
    attribution: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(500))
    remixed_from_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
