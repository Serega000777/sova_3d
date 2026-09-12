"""Assets, project versions and their links (T-008).

Invariants enforced in PostgreSQL (see migration 0002):
- assets are immutable: only `metadata` may change after insert.
- a finalized project_version cannot be updated or deleted.
- version_assets for a finalized version are frozen for content roles
  (source/model/scan); regenerable roles (preview/export) may still be attached.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey
from app.models.core import Project, Units, User, Workspace


class AssetKind(enum.StrEnum):
    original = "original"
    derived = "derived"


class VersionState(enum.StrEnum):
    draft = "draft"
    finalized = "finalized"


class AssetRole(enum.StrEnum):
    source = "source"
    model = "model"
    preview = "preview"
    export = "export"
    scan = "scan"


CONTENT_ROLES = frozenset({AssetRole.source, AssetRole.model, AssetRole.scan})


class Asset(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_assets_workspace_sha256"),
        Index("ix_assets_sha256", "sha256"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind, name="asset_kind"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str | None] = mapped_column(String(32))
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    units: Mapped[Units | None] = mapped_column(Enum(Units, name="units", create_type=False))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    workspace: Mapped[Workspace] = relationship()
    creator: Mapped[User | None] = relationship()


class ProjectVersion(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "project_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence_no", name="uq_project_versions_project_sequence"),
        Index("ix_project_versions_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="RESTRICT")
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[VersionState] = mapped_column(
        Enum(VersionState, name="version_state"),
        nullable=False,
        server_default=VersionState.draft.value,
    )
    label: Mapped[str | None] = mapped_column(String(200))
    # source version, operation ids, ai_request ids — every derived version is traceable.
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(foreign_keys=[project_id])
    parent: Mapped["ProjectVersion | None"] = relationship(remote_side="ProjectVersion.id")
    assets: Mapped[list["VersionAsset"]] = relationship(back_populates="version")


class VersionAsset(CreatedAt, Base):
    __tablename__ = "version_assets"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[AssetRole] = mapped_column(Enum(AssetRole, name="asset_role"), primary_key=True)

    version: Mapped[ProjectVersion] = relationship(back_populates="assets")
    asset: Mapped[Asset] = relationship()
