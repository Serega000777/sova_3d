"""Immutable, server-owned interior finish catalogue."""

from app.interior_materials.catalog import (
    InteriorMaterial,
    all_materials,
    material_by_id,
    snapshot_for,
    texture_bytes,
    validate_snapshot,
)

__all__ = [
    "InteriorMaterial",
    "all_materials",
    "material_by_id",
    "snapshot_for",
    "texture_bytes",
    "validate_snapshot",
]
