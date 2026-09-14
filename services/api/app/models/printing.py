"""Printing domain (E7/E8): printer catalogue, materials, workspace printer profiles, analyses."""

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class Technology(enum.StrEnum):
    fdm = "fdm"
    resin = "resin"


class PrinterModel(CreatedAt, Base):
    """Catalogue entry (T-068): what a machine of this model can do out of the box."""

    __tablename__ = "printer_models"
    __table_args__ = (UniqueConstraint("vendor", "model", name="uq_printer_models_vendor_model"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "bambu-x1c"
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    technology: Mapped[Technology] = mapped_column(
        Enum(Technology, name="print_technology"), nullable=False
    )
    bed_x_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    bed_y_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    bed_z_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    nozzle_mm: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    max_overhang_deg: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, server_default=text("45")
    )
    print_speed_mm_s: Mapped[Decimal] = mapped_column(
        Numeric(6, 1), nullable=False, server_default=text("60")
    )


class Material(CreatedAt, Base):
    """Material profile (T-069): density, price, shrinkage, minimum wall."""

    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "pla"
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    density_g_cm3: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    price_per_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    shrinkage_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    min_wall_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(String(255))


class PrinterProfile(UUIDPrimaryKey, Timestamps, Base):
    """A concrete machine in a workspace (T-070): model defaults + calibration overrides."""

    __tablename__ = "printer_profiles"
    __table_args__ = (Index("ix_printer_profiles_workspace", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    printer_model_id: Mapped[str] = mapped_column(
        ForeignKey("printer_models.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    nozzle_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    layer_height_mm: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("0.2")
    )
    max_overhang_deg: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    print_speed_mm_s: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    default_material_id: Mapped[str | None] = mapped_column(
        ForeignKey("materials.id", ondelete="SET NULL")
    )
    calibration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    printer_model: Mapped[PrinterModel] = relationship()


class AnalysisKind(enum.StrEnum):
    analysis = "analysis"
    optimize = "optimize"


class PrintAnalysisRecord(UUIDPrimaryKey, CreatedAt, Base):
    """Stored result of analyze-print / optimize-print (T-064/T-067)."""

    __tablename__ = "print_analyses"
    __table_args__ = (
        Index("ix_print_analyses_version_created", "project_version_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    printer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("printer_profiles.id", ondelete="SET NULL")
    )
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"))
    kind: Mapped[AnalysisKind] = mapped_column(
        Enum(AnalysisKind, name="print_analysis_kind"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)  # green | yellow | red
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
