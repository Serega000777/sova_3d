"""Asset lookups shared by the API and job handlers (no compute-library imports here)."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset

REPAIRABLE_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})


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
