"""The bridge itself: open the device, open a session, stream, finalize, hand over."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from physical_ai_scanner.client import ApiError, ScanClient
from physical_ai_scanner.drivers.base import Driver, Fragment

Log = Callable[[str], None]


@dataclass
class BridgeResult:
    scan_id: str
    fragments: int = 0
    points: int = 0
    faces: int = 0
    status: str = "capturing"
    version_id: str | None = None
    project_id: str | None = None
    report: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def run_scan(
    client: ScanClient,
    driver: Driver,
    *,
    workspace_id: str,
    label: str | None = None,
    project_id: str | None = None,
    accept: bool = True,
    log: Log = print,
) -> BridgeResult:
    """Stream what the device delivers into a session, then reconstruct and (optionally)
    accept the result into a project. Every fragment reaches the platform the moment the
    device hands it over, so the Scanner section shows the model growing."""
    device = driver.open()
    log(f"device: {device.vendor} {device.model} ({device.driver})")
    session = client.create_session(
        workspace_id, device=device.to_dict(), label=label, project_id=project_id
    )
    result = BridgeResult(scan_id=str(session["id"]))
    log(f"session {result.scan_id} open — scanning")
    try:
        for fragment in driver.fragments():
            _send(client, workspace_id, result, fragment, log)
    except KeyboardInterrupt:
        log("stopped by hand — finishing with what arrived")
    finally:
        driver.close()

    if result.fragments == 0:
        client.cancel(result.scan_id)
        result.status = "canceled"
        result.error = "the device delivered nothing"
        log(result.error)
        return result

    client.capture_stats(
        result.scan_id,
        {"fragments": result.fragments, "points": result.points, "faces": result.faces},
    )
    log(f"{result.fragments} fragment(s) sent — reconstructing")
    try:
        job = client.finalize(result.scan_id)
        done = client.wait_for_job(str(job["job_id"]))
    except ApiError as exc:
        result.status = "failed"
        result.error = exc.message
        log(f"reconstruction failed: {exc.message}")
        return result
    if done.get("status") != "succeeded":
        error = done.get("error") or {}
        result.status = "failed"
        result.error = str(error.get("message") or done.get("status"))
        log(f"reconstruction failed: {result.error}")
        return result

    scan = client.scan(result.scan_id)
    result.report = dict(scan.get("report") or {})
    result.status = str(scan.get("status"))
    scale = result.report.get("scale") or {}
    log(
        f"model ready: {scale.get('applied_mm', '?')} mm across "
        f"(scale from {scale.get('source', '?')}, confidence {scale.get('confidence', '?')})"
    )
    if accept:
        try:
            target = project_id
            if target is None:  # a scan with nowhere to go gets a project named after it
                project = client.create_project(workspace_id, label or "Scanned object")
                target = str(project["id"])
                log(f"project made for it: {target}")
            kept = client.accept(result.scan_id, label=label, project_id=target)
        except ApiError as exc:
            result.error = f"the model is ready but could not be added: {exc.message}"
            log(result.error)
            return result
        result.status = str(kept.get("status"))
        result.version_id = kept.get("result_version_id")
        result.project_id = kept.get("project_id")
        log(f"in the workspace: project {result.project_id}, version {result.version_id}")
    return result


def _send(
    client: ScanClient, workspace_id: str, result: BridgeResult, fragment: Fragment, log: Log
) -> None:
    asset_id = client.upload(workspace_id, fragment.filename, fragment.content_type, fragment.data)
    client.add_frame(
        result.scan_id,
        asset_id=asset_id,
        sequence_no=fragment.sequence_no,
        kind=fragment.kind,
        pose=fragment.pose,
        quality=fragment.quality,
    )
    result.fragments += 1
    result.points += int(fragment.quality.get("points") or 0)
    result.faces += int(fragment.quality.get("faces") or 0)
    where = fragment.pose.get("azimuth_deg")
    angle = f" at {float(where):.0f}°" if isinstance(where, (int, float)) else ""
    log(f"fragment {fragment.sequence_no}{angle}: {len(fragment.data) // 1024} KB sent")
