"""Append-only usage ledger (T-010). Aggregates are computed, never stored here."""

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class UsageKind(enum.StrEnum):
    ai_tokens = "ai_tokens"
    gpu_seconds = "gpu_seconds"
    cpu_seconds = "cpu_seconds"
    storage_bytes = "storage_bytes"
    credits = "credits"


class UsageEntry(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (
        Index("ix_usage_ledger_workspace_created", "workspace_id", "created_at"),
        CheckConstraint("quantity >= 0", name="ck_usage_ledger_quantity_nonnegative"),
        CheckConstraint("cost_usd >= 0", name="ck_usage_ledger_cost_nonnegative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="SET NULL")
    )

    kind: Mapped[UsageKind] = mapped_column(Enum(UsageKind, name="usage_kind"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    # Credits are signed: consumption is negative, top-ups/refunds positive.
    credits_delta: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, server_default=text("0")
    )
    # provider/model/version, stage — whatever makes the row attributable.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
