"""printer_models, materials, printer_profiles, print_analyses + seed data (T-064/T-068..T-070)

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

technology = postgresql.ENUM("fdm", "resin", name="print_technology", create_type=False)
analysis_kind = postgresql.ENUM(
    "analysis", "optimize", name="print_analysis_kind", create_type=False
)
TIMESTAMPTZ = sa.DateTime(timezone=True)

# (id, vendor, model, tech, bed x, y, z, nozzle, max overhang, speed) — T-068 initial set.
PRINTER_MODELS = [
    ("bambu-x1c", "Bambu Lab", "X1 Carbon", "fdm", 256, 256, 256, 0.4, 45, 120),
    ("bambu-p1s", "Bambu Lab", "P1S", "fdm", 256, 256, 256, 0.4, 45, 120),
    ("bambu-a1", "Bambu Lab", "A1", "fdm", 256, 256, 256, 0.4, 45, 100),
    ("bambu-a1-mini", "Bambu Lab", "A1 mini", "fdm", 180, 180, 180, 0.4, 45, 100),
    ("prusa-mk4", "Prusa", "MK4", "fdm", 250, 210, 220, 0.4, 45, 100),
    ("prusa-mini", "Prusa", "MINI+", "fdm", 180, 180, 180, 0.4, 45, 80),
    ("prusa-xl", "Prusa", "XL", "fdm", 360, 360, 360, 0.4, 45, 100),
    ("creality-ender3-v3", "Creality", "Ender-3 V3", "fdm", 220, 220, 250, 0.4, 45, 80),
    ("creality-k1", "Creality", "K1", "fdm", 220, 220, 250, 0.4, 45, 120),
    ("creality-k1-max", "Creality", "K1 Max", "fdm", 300, 300, 300, 0.4, 45, 120),
]

# (id, name, kind, density g/cm3, price/kg USD, shrinkage %, min wall mm, notes) — T-069.
MATERIALS = [
    ("pla", "PLA", "PLA", 1.24, 25, 0.3, 0.8, "Easiest to print; low heat resistance"),
    ("petg", "PETG", "PETG", 1.27, 28, 0.4, 0.8, "Tougher, slightly stringy"),
    ("abs", "ABS", "ABS", 1.04, 26, 0.8, 1.0, "Needs an enclosure; warps"),
    ("tpu", "TPU 95A", "TPU", 1.21, 40, 0.6, 1.2, "Flexible; slow printing"),
    ("asa", "ASA", "ASA", 1.07, 32, 0.7, 1.0, "UV resistant ABS alternative"),
]


def upgrade() -> None:
    technology.create(op.get_bind(), checkfirst=True)
    analysis_kind.create(op.get_bind(), checkfirst=True)

    printer_models = op.create_table(
        "printer_models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("vendor", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("technology", technology, nullable=False),
        sa.Column("bed_x_mm", sa.Numeric(8, 2), nullable=False),
        sa.Column("bed_y_mm", sa.Numeric(8, 2), nullable=False),
        sa.Column("bed_z_mm", sa.Numeric(8, 2), nullable=False),
        sa.Column("nozzle_mm", sa.Numeric(4, 2), nullable=False),
        sa.Column("max_overhang_deg", sa.Numeric(4, 1), nullable=False, server_default="45"),
        sa.Column("print_speed_mm_s", sa.Numeric(6, 1), nullable=False, server_default="60"),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vendor", "model", name="uq_printer_models_vendor_model"),
    )
    materials = op.create_table(
        "materials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("density_g_cm3", sa.Numeric(6, 3), nullable=False),
        sa.Column("price_per_kg", sa.Numeric(8, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("shrinkage_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("min_wall_mm", sa.Numeric(5, 2)),
        sa.Column("notes", sa.String(255)),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "printer_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_printer_profiles_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_printer_profiles_user_id_users"
            ),
        ),
        sa.Column(
            "printer_model_id",
            sa.String(64),
            sa.ForeignKey(
                "printer_models.id",
                ondelete="RESTRICT",
                name="fk_printer_profiles_printer_model_id_printer_models",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("nozzle_mm", sa.Numeric(4, 2)),
        sa.Column("layer_height_mm", sa.Numeric(4, 2), nullable=False, server_default="0.2"),
        sa.Column("max_overhang_deg", sa.Numeric(4, 1)),
        sa.Column("print_speed_mm_s", sa.Numeric(6, 1)),
        sa.Column(
            "default_material_id",
            sa.String(64),
            sa.ForeignKey(
                "materials.id",
                ondelete="SET NULL",
                name="fk_printer_profiles_default_material_id_materials",
            ),
        ),
        sa.Column(
            "calibration",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_printer_profiles_workspace", "printer_profiles", ["workspace_id"])

    op.create_table(
        "print_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id",
                ondelete="CASCADE",
                name="fk_print_analyses_workspace_id_workspaces",
            ),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="CASCADE",
                name="fk_print_analyses_project_version_id_project_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(
                "assets.id", ondelete="SET NULL", name="fk_print_analyses_asset_id_assets"
            ),
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL", name="fk_print_analyses_job_id_jobs"),
        ),
        sa.Column(
            "printer_profile_id",
            sa.Uuid(),
            sa.ForeignKey(
                "printer_profiles.id",
                ondelete="SET NULL",
                name="fk_print_analyses_printer_profile_id_printer_profiles",
            ),
        ),
        sa.Column(
            "material_id",
            sa.String(64),
            sa.ForeignKey(
                "materials.id", ondelete="SET NULL", name="fk_print_analyses_material_id_materials"
            ),
        ),
        sa.Column("kind", analysis_kind, nullable=False),
        sa.Column("score", sa.Numeric(5, 1), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column(
            "result_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "project_versions.id",
                ondelete="SET NULL",
                name="fk_print_analyses_result_version_id_project_versions",
            ),
        ),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_print_analyses_version_created", "print_analyses", ["project_version_id", "created_at"]
    )

    op.bulk_insert(
        printer_models,
        [
            {
                "id": pid,
                "vendor": vendor,
                "model": model,
                "technology": tech,
                "bed_x_mm": x,
                "bed_y_mm": y,
                "bed_z_mm": z,
                "nozzle_mm": nozzle,
                "max_overhang_deg": overhang,
                "print_speed_mm_s": speed,
            }
            for pid, vendor, model, tech, x, y, z, nozzle, overhang, speed in PRINTER_MODELS
        ],
    )
    op.bulk_insert(
        materials,
        [
            {
                "id": mid,
                "name": name,
                "kind": kind,
                "density_g_cm3": density,
                "price_per_kg": price,
                "currency": "USD",
                "shrinkage_pct": shrink,
                "min_wall_mm": wall,
                "notes": notes,
            }
            for mid, name, kind, density, price, shrink, wall, notes in MATERIALS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_print_analyses_version_created", table_name="print_analyses")
    op.drop_table("print_analyses")
    op.drop_index("ix_printer_profiles_workspace", table_name="printer_profiles")
    op.drop_table("printer_profiles")
    op.drop_table("materials")
    op.drop_table("printer_models")
    analysis_kind.drop(op.get_bind(), checkfirst=True)
    technology.drop(op.get_bind(), checkfirst=True)
