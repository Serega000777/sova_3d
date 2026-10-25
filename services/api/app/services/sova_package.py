"""Deterministic, buyer-owned Sova project packages.

``.sova`` is a ZIP-based interchange container owned by this product.  It contains the
immutable acquired project/version record, the exact operation stack and every concrete
source/model/export file delivered into the buyer's workspace.  Database hashes and sizes are
verified while the archive is built; corrupt or missing object storage never produces a package.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from typing import Any

from app.api.errors import ValidationFailedError
from app.services.marketplace import MarketplaceOrderDelivery
from app.storage import ObjectStorage

SOVA_MIME = "application/vnd.sova.project+zip"
SOVA_SCHEMA_VERSION = 1
_SAFE_EXTENSION = re.compile(r"^[a-z0-9][a-z0-9+_-]{0,15}$")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _entry(name: str, *, compressed: bool = True) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    info.external_attr = 0o600 << 16
    return info


def _extension(value: str | None) -> str:
    candidate = (value or "bin").strip().lower().lstrip(".")
    return candidate if _SAFE_EXTENSION.fullmatch(candidate) else "bin"


def render_sova_package(
    delivery: MarketplaceOrderDelivery, storage: ObjectStorage
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Build a seeked spooled file suitable for a streaming HTTP response."""
    grouped: dict[str, dict[str, Any]] = {}
    for delivered in delivery.files:
        key = str(delivered.asset.id)
        row = grouped.setdefault(
            key,
            {
                "asset": delivered.asset,
                "roles": [],
                "labels": [],
            },
        )
        role = delivered.role.value
        if role not in row["roles"]:
            row["roles"].append(role)
        for label in delivered.labels:
            if label not in row["labels"]:
                row["labels"].append(label)

    manifest_assets: list[dict[str, Any]] = []
    for asset_id in sorted(grouped):
        row = grouped[asset_id]
        asset = row["asset"]
        extension = _extension(asset.format)
        manifest_assets.append(
            {
                "asset_id": asset_id,
                "path": f"assets/{asset_id}.{extension}",
                "roles": sorted(row["roles"]),
                "labels": row["labels"],
                "format": asset.format,
                "mime": asset.mime,
                "byte_size": asset.byte_size,
                "sha256": asset.sha256,
                "units": asset.units.value if asset.units is not None else None,
            }
        )

    version = delivery.version
    project = delivery.project
    project_record = {
        "schema_version": SOVA_SCHEMA_VERSION,
        "project": {
            "id": str(project.id),
            "workspace_id": str(project.workspace_id),
            "name": project.name,
            "description": project.description,
            "units": project.units.value,
            "license_id": project.license_id,
            "attribution": project.attribution,
            "source_url": project.source_url,
            "remixed_from_project_id": (
                str(project.remixed_from_project_id) if project.remixed_from_project_id else None
            ),
        },
        "version": {
            "id": str(version.id),
            "sequence_no": version.sequence_no,
            "state": version.state.value,
            "label": version.label,
            "parent_version_id": (
                str(version.parent_version_id) if version.parent_version_id else None
            ),
            "created_at": version.created_at.isoformat(),
            "finalized_at": version.finalized_at.isoformat() if version.finalized_at else None,
            "provenance": version.provenance,
        },
        "operations": [
            {
                "id": str(operation.id),
                "sequence_no": operation.sequence_no,
                "type": operation.operation_type,
                "schema_version": operation.schema_version,
                "enabled": operation.enabled,
                "params": operation.params,
                "entity_refs": operation.entity_refs,
            }
            for operation in delivery.operations
        ],
    }
    manifest = {
        "format": "sova-project-package",
        "schema_version": SOVA_SCHEMA_VERSION,
        "order_id": str(delivery.order.id),
        "listing_id": str(delivery.item.id),
        "project_record": "project.json",
        "assets": manifest_assets,
    }

    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
            archive.writestr(_entry("mimetype", compressed=False), SOVA_MIME.encode("ascii"))
            archive.writestr(_entry("manifest.json"), _json_bytes(manifest))
            archive.writestr(_entry("project.json"), _json_bytes(project_record))
            by_id = {str(row["asset"].id): row["asset"] for row in grouped.values()}
            for descriptor in manifest_assets:
                asset = by_id[descriptor["asset_id"]]
                digest = hashlib.sha256()
                byte_size = 0
                with archive.open(_entry(descriptor["path"]), "w") as target:
                    for chunk in storage.iter_chunks(asset.storage_key):
                        target.write(chunk)
                        digest.update(chunk)
                        byte_size += len(chunk)
                if byte_size != asset.byte_size or digest.hexdigest() != asset.sha256:
                    raise ValidationFailedError(
                        "delivered asset failed integrity verification",
                        {"asset_id": str(asset.id)},
                    )
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise
