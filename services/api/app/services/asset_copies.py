"""Cross-workspace copies of immutable, content-addressed assets."""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.versioning import Asset
from app.services.content_addressed_assets import lock_content_addressed_assets
from app.storage import ObjectStorage


def copy_asset_to_workspace(
    db: Session,
    storage: ObjectStorage,
    asset: Asset,
    *,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID,
) -> Asset:
    """Copy one immutable asset into another workspace, reusing identical bytes there."""
    lock_content_addressed_assets(db, workspace_id=workspace_id, sha256s=(asset.sha256,))
    existing = db.scalar(
        sa.select(Asset).where(Asset.workspace_id == workspace_id, Asset.sha256 == asset.sha256)
    )
    if existing is not None:
        return existing
    extension = asset.storage_key.rsplit(".", 1)[-1] if "." in asset.storage_key else "bin"
    key = storage.object_key(workspace_id, asset.sha256, extension)
    storage.copy(asset.storage_key, key)
    copied = Asset(
        workspace_id=workspace_id,
        kind=asset.kind,
        sha256=asset.sha256,
        storage_key=key,
        mime=asset.mime,
        format=asset.format,
        byte_size=asset.byte_size,
        units=asset.units,
        metadata_={**(asset.metadata_ or {}), "copied_from_asset_id": str(asset.id)},
        created_by=created_by,
    )
    db.add(copied)
    db.flush()
    return copied
