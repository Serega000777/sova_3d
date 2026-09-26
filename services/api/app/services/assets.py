"""Asset lookups shared by the API and job handlers (no compute-library imports here)."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset

REPAIRABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})


def brep_asset_of(db: Session, version: ProjectVersion) -> Asset | None:
    """The version's exact geometry (F-078): the kernel's B-Rep in the `source` role."""
    link = db.scalar(
        sa.select(VersionAsset).where(
            VersionAsset.version_id == version.id, VersionAsset.role == AssetRole.source
        )
    )
    if link is None:
        return None
    asset = db.get(Asset, link.asset_id)
    return asset if asset is not None and asset.format == "brep" else None


def model_asset_of(db: Session, version: ProjectVersion) -> Asset | None:
    """The version's editable geometry: `model` role first, then `source`."""
    for role in (AssetRole.model, AssetRole.source):
        link = db.scalar(
            sa.select(VersionAsset).where(
                VersionAsset.version_id == version.id, VersionAsset.role == role
            )
        )
        if link is not None:
            return db.get(Asset, link.asset_id)
    return None


def preview_asset_of(db: Session, version: ProjectVersion) -> Asset | None:
    """The painted preview (F-034), when the version has one: the model with its colours."""
    link = db.scalar(
        sa.select(VersionAsset).where(
            VersionAsset.version_id == version.id, VersionAsset.role == AssetRole.preview
        )
    )
    return db.get(Asset, link.asset_id) if link is not None else None
