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
MAX_CAMERA_BYTES = 10 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class PrinterState:
    provider: Literal["stub", "octoprint"]
    state: str
    operational: bool
    printing: bool
    paused: bool
    completion_pct: float | None
    elapsed_seconds: int | None
    remaining_seconds: int | None
    filename: str | None
    nozzle_actual_c: float | None
    nozzle_target_c: float | None
    bed_actual_c: float | None
    bed_target_c: float | None


def capability(settings: Settings) -> dict[str, object]:
    provider = settings.printer_bridge_provider
    return {
        "enabled": provider != "none",
        "provider": provider,
        "test_mode": provider == "stub",
        "can_start": provider != "none",
        "has_camera": provider != "none",
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


def _get_json(
    settings: Settings, path: str, *, allow_not_operational: bool = False
) -> dict[str, object]:
    try:
        response = httpx.get(
            f"{(settings.octoprint_url or '').rstrip('/')}{path}",
            headers={"X-Api-Key": settings.octoprint_api_key or ""},
            timeout=settings.octoprint_timeout_seconds,
            verify=settings.octoprint_verify_tls,
        )
        if allow_not_operational and response.status_code == 409:
            return {}
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, dict) else {}
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise PrinterBridgeUnavailableError(
            "printer controller status is unavailable",
            {"provider": "octoprint", "reason": type(exc).__name__},
        ) from exc


def printer_state(settings: Settings) -> PrinterState:
    provider = settings.printer_bridge_provider
    if provider == "none":
        raise PrinterBridgeNotEnabledError("printer connection is not configured")
    if provider == "stub":
        return PrinterState(
            provider="stub",
            state="Ready · test mode",
            operational=True,
            printing=False,
            paused=False,
            completion_pct=0.0,
            elapsed_seconds=0,
            remaining_seconds=None,
            filename=None,
            nozzle_actual_c=24.0,
            nozzle_target_c=0.0,
            bed_actual_c=23.0,
            bed_target_c=0.0,
        )

    job = _get_json(settings, "/api/job")
    printer = _get_json(settings, "/api/printer", allow_not_operational=True)

    def mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items()}

    progress = mapping(job.get("progress"))
    job_info = mapping(job.get("job"))
    file_info = mapping(job_info.get("file"))
    printer_state_body = mapping(printer.get("state"))
    flags = mapping(printer_state_body.get("flags"))
    temperatures = mapping(printer.get("temperature"))
    tool = mapping(temperatures.get("tool0"))
    bed = mapping(temperatures.get("bed"))

    def number(value: object) -> float | None:
        return float(value) if isinstance(value, int | float) else None

    def seconds(value: object) -> int | None:
        return int(value) if isinstance(value, int | float) else None

    return PrinterState(
        provider="octoprint",
        state=str(job.get("state") or printer_state_body.get("text") or "Unknown"),
        operational=bool(flags.get("operational")),
        printing=bool(flags.get("printing")),
        paused=bool(flags.get("paused")),
        completion_pct=number(progress.get("completion")),
        elapsed_seconds=seconds(progress.get("printTime")),
        remaining_seconds=seconds(progress.get("printTimeLeft")),
        filename=str(file_info.get("name")) if file_info.get("name") else None,
        nozzle_actual_c=number(tool.get("actual")),
        nozzle_target_c=number(tool.get("target")),
        bed_actual_c=number(bed.get("actual")),
        bed_target_c=number(bed.get("target")),
    )


def camera_snapshot(settings: Settings) -> tuple[bytes, str]:
    provider = settings.printer_bridge_provider
    if provider == "none":
        raise PrinterBridgeNotEnabledError("printer connection is not configured")
    if provider == "stub":
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"
 viewBox="0 0 960 540"><rect width="960" height="540" fill="#0b1020"/>
<circle cx="480" cy="250" r="112" fill="none" stroke="#38bdf8" stroke-width="5"/>
<path d="M405 330h150l-18 70H423z" fill="#18233a" stroke="#38bdf8" stroke-width="4"/>
<text x="480" y="90" fill="#e2e8f0" font-family="sans-serif" font-size="34"
 text-anchor="middle">Printer camera - DEMO</text><text x="480" y="480" fill="#94a3b8"
 font-family="sans-serif" font-size="22" text-anchor="middle">No real camera was contacted</text>
</svg>"""
        return svg.encode(), "image/svg+xml"
    default_camera = f"{(settings.octoprint_url or '').rstrip('/')}/webcam/?action=snapshot"
    url = settings.octoprint_camera_url or default_camera
    try:
        response = httpx.get(
            url,
            headers={"X-Api-Key": settings.octoprint_api_key or ""},
            timeout=settings.octoprint_timeout_seconds,
            verify=settings.octoprint_verify_tls,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        raise PrinterBridgeUnavailableError(
            "printer camera is unavailable",
            {"provider": "octoprint", "reason": type(exc).__name__},
        ) from exc
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/") or len(response.content) > MAX_CAMERA_BYTES:
        raise PrinterBridgeUnavailableError("printer camera returned an invalid image")
    return response.content, content_type
