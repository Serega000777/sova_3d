"""Presigned upload sessions (T-012): staged objects awaiting hash verification."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class UploadStatus(enum.StrEnum):
    pending = "pending"
    completed = "completed"
    rejected = "rejected"


class UploadSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_upload_sessions_workspace_idempotency"
        ),
        Index("ix_upload_sessions_workspace_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format_id: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_status"),
        nullable=False,
        server_default=UploadStatus.pending.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
