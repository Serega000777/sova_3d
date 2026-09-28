"""Server-side printer-controller bridge (F-056).

Only operator configuration chooses the remote address and API key. Requests can
select an existing workspace G-code asset and whether OctoPrint should start it.
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.api.errors import APIError, NotFoundError, PayloadTooLargeError, ValidationFailedError
from app.config import Settings
from app.models.core import WorkspaceRole
from app.models.versioning import Asset
from app.services import authz
from app.storage import ObjectStorage

MAX_GCODE_BYTES = 256 * 1024 * 1024


class PrinterBridgeNotEnabledError(APIError):
    status_code = 501
    code = "printer_bridge_not_enabled"


class PrinterBridgeUnavailableError(APIError):
    status_code = 502
    code = "printer_bridge_unavailable"


@dataclass(frozen=True, slots=True)
class PrintDispatch:
    provider: Literal["stub", "octoprint"]
    filename: str
    selected: bool
    printing: bool
    remote_path: str
    message: str


def capability(settings: Settings) -> dict[str, object]:
    provider = settings.printer_bridge_provider
    return {
        "enabled": provider != "none",
        "provider": provider,
        "test_mode": provider == "stub",
        "can_start": provider != "none",
    }


def _safe_filename(asset: Asset) -> str:
    raw = str((asset.metadata_ or {}).get("filename") or f"model-{asset.id}.gcode")
    name = PurePath(raw.replace("\\", "/")).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or f"model-{asset.id}"
    return stem if stem.lower().endswith(".gcode") else f"{stem}.gcode"


def dispatch_gcode(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    asset_id: uuid.UUID,
    start: bool,
) -> PrintDispatch:
    authz.require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise NotFoundError("asset", asset_id)
    if (asset.format or "").lower() != "gcode":
        raise ValidationFailedError("only a G-code asset can be sent to a printer")
    if asset.byte_size > MAX_GCODE_BYTES:
        raise PayloadTooLargeError("G-code is too large for direct printer upload")

    provider = settings.printer_bridge_provider
    if provider == "none":
        raise PrinterBridgeNotEnabledError("printer connection is not configured")
    filename = _safe_filename(asset)
    if provider == "stub":
        return PrintDispatch(
            provider="stub",
            filename=filename,
            selected=True,
            printing=start,
            remote_path=f"local/{filename}",
            message="Test upload completed; no real printer was contacted.",
        )

    payload = storage.get(asset.storage_key)
    url = f"{(settings.octoprint_url or '').rstrip('/')}/api/files/local"
    try:
        response = httpx.post(
            url,
            headers={"X-Api-Key": settings.octoprint_api_key or ""},
            data={"select": "true", "print": "true" if start else "false"},
            files={"file": (filename, payload, "text/x-gcode")},
            timeout=settings.octoprint_timeout_seconds,
            verify=settings.octoprint_verify_tls,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        raise PrinterBridgeUnavailableError(
            "printer controller did not accept the G-code",
            {"provider": "octoprint", "reason": type(exc).__name__},
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    remote_path = str(((body.get("files") or {}).get("local") or {}).get("path") or filename)
    return PrintDispatch(
        provider="octoprint",
        filename=filename,
        selected=True,
        printing=start,
        remote_path=remote_path,
        message="G-code uploaded and print started." if start else "G-code uploaded to OctoPrint.",
    )
