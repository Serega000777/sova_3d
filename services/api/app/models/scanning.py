"""Scan domain (E9, F-002): a capture session, its frames, and the reconstruction result.

A session is a long-lived, resumable thing: a phone uploads frames one at a time over a
flaky link (T-078), so each frame is its own row keyed by the client's sequence number.
Finalizing the session (T-079) queues the reconstruction job; the session then owns the
outcome — the mesh asset, the scale report, and the version the user accepted.
"""

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class ScanStatus(enum.StrEnum):
    capturing = "capturing"
    uploading = "uploading"
    reconstructing = "reconstructing"
    ready = "ready"
    accepted = "accepted"
    failed = "failed"
    canceled = "canceled"


class ScanMode(enum.StrEnum):
    """How the frames were captured — what the device could actually do (T-074)."""

    rgb = "rgb"  # plain photos; works in Expo Go
    rgb_depth = "rgb_depth"  # ARKit/ARCore depth + pose, development build only


class FrameKind(enum.StrEnum):
    rgb = "rgb"
    depth = "depth"


class ScanSession(Timestamps, UUIDPrimaryKey, Base):
    __tablename__ = "scan_sessions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_scan_sessions_workspace_idempotency"
        ),
        Index("ix_scan_sessions_workspace_created", "workspace_id", "created_at"),
        Index("ix_scan_sessions_project", "project_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))

    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"),
        nullable=False,
        server_default=ScanStatus.capturing.value,
    )
    mode: Mapped[ScanMode] = mapped_column(
        Enum(ScanMode, name="scan_mode"), nullable=False, server_default=ScanMode.rgb.value
    )
    label: Mapped[str | None] = mapped_column(String(200))
    # What the device reported it could do, verbatim, so a bad reconstruction can be explained.
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Guided-capture progress the client keeps updated (T-075): coverage, blur, frame count.
    capture_stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    mesh_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
    # Reconstruction report: provider, mesh stats, repair report (T-083), scale check (T-082).
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Metric scale the client believes in, and how sure it is (T-082).
    scale_hint_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    scale_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ScanFrame(CreatedAt, UUIDPrimaryKey, Base):
    """One uploaded frame. `sequence_no` is the client's, so a retry is idempotent (T-078)."""

    __tablename__ = "scan_frames"
    __table_args__ = (
        UniqueConstraint(
            "scan_session_id", "sequence_no", "kind", name="uq_scan_frames_session_sequence_kind"
        ),
        Index("ix_scan_frames_session_sequence", "scan_session_id", "sequence_no"),
    )

    scan_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_sessions.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[FrameKind] = mapped_column(
        Enum(FrameKind, name="scan_frame_kind"), nullable=False, server_default=FrameKind.rgb.value
    )
    # Camera pose + intrinsics when the device has them (ARKit/ARCore), else empty.
    pose: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Guided-capture measurements for this frame: sharpness, exposure, angle (T-075).
    quality: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
