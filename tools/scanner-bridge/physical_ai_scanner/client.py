"""The platform's scan session API, the client's own way: presign, PUT, complete, frame.

Standard library only, so the bridge installs anywhere a scanner's software runs.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message
        self.code = code


RETRIES = 4  # a scanner PC and the server share a network that hiccups; frames are idempotent


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            if attempt == RETRIES - 1:
                raise ApiError(0, f"{url}: {exc}") from exc
            time.sleep(0.5 * 2**attempt)  # 0.5, 1, 2 s: enough for a proxy to come back
    raise ApiError(0, f"{url}: gave up")  # unreachable; keeps the type checker honest


class ScanClient:
    def __init__(self, base_url: str, token: str, transport: Transport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport or _urllib_transport

    # --- plumbing -------------------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        status, raw = self._transport(method, self.base_url + path, headers, payload)
        if status >= 400:
            try:
                error = json.loads(raw).get("error", {})
            except ValueError:
                error = {}
            raise ApiError(
                status,
                error.get("message") or raw[:200].decode("utf-8", "replace"),
                error.get("code"),
            )
        return json.loads(raw) if raw else None

    def upload(self, workspace_id: str, filename: str, content_type: str, data: bytes) -> str:
        created = self._call(
            "POST",
            "/api/v1/uploads",
            {
                "workspace_id": workspace_id,
                "filename": filename,
                "content_type": content_type,
                "byte_size": len(data),
            },
        )
        put_headers = {"Content-Type": content_type, **created.get("headers", {})}
        status, raw = self._transport("PUT", created["url"], put_headers, data)
        if status >= 300:
            raise ApiError(status, f"upload of {filename} failed")
        asset = self._call(
            "POST",
            "/api/v1/assets/complete",
            {"upload_id": created["upload_id"], "sha256": hashlib.sha256(data).hexdigest()},
        )
        return str(asset["id"])

    # --- the session ----------------------------------------------------------------------

    def create_session(
        self,
        workspace_id: str,
        *,
        device: dict[str, Any],
        label: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST",
            "/api/v1/scans",
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "mode": "scanner",
                "label": label,
                "capabilities": {"device": device},
            },
        )
        return result

    def add_frame(
        self,
        scan_id: str,
        *,
        asset_id: str,
        sequence_no: int,
        kind: str,
        pose: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST",
            f"/api/v1/scans/{scan_id}/frames",
            {
                "asset_id": asset_id,
                "sequence_no": sequence_no,
                "kind": kind,
                "pose": pose,
                "quality": quality,
            },
        )
        return result

    def capture_stats(self, scan_id: str, stats: dict[str, Any]) -> None:
        self._call("PATCH", f"/api/v1/scans/{scan_id}/capture-stats", {"stats": stats})

    def finalize(self, scan_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call("POST", f"/api/v1/scans/{scan_id}/finalize", {})
        return result

    def job(self, job_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call("GET", f"/api/v1/jobs/{job_id}")
        return result

    def wait_for_job(
        self, job_id: str, *, timeout_s: float = 600.0, poll_s: float = 2.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while True:
            job = self.job(job_id)
            if job.get("status") in ("succeeded", "failed", "canceled"):
                return job
            if time.monotonic() > deadline:
                raise ApiError(504, f"job {job_id} did not finish in {timeout_s:.0f}s")
            time.sleep(poll_s)

    def scan(self, scan_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call("GET", f"/api/v1/scans/{scan_id}")
        return result

    def accept(
        self, scan_id: str, *, label: str | None = None, project_id: str | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST", f"/api/v1/scans/{scan_id}/accept", {"label": label, "project_id": project_id}
        )
        return result

    def cancel(self, scan_id: str) -> None:
        self._call("POST", f"/api/v1/scans/{scan_id}/cancel")

    def create_project(self, workspace_id: str, name: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST", "/api/v1/projects", {"workspace_id": workspace_id, "name": name}
        )
        return result
