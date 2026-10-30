"""Narrow MCP facade over Sova's provider-neutral 3D generation API.

The MCP process deliberately owns no database, object-storage, or Blender access. The existing
HTTP API remains the authentication, workspace-isolation, validation, and job-orchestration
boundary; this facade additionally restricts the process to an explicit project allowlist.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

from app.ai.three_d import (
    GenerationBenchmarkReport,
    GenerationEstimate,
    GenerationRequest,
    ProviderCapabilities,
)
from app.api.schemas import JobAccepted
from app.api.three_d_generation import ThreeDGenerationOut

_DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
_MAX_RESPONSE_BYTES = 1_048_576
_REQUEST_TIMEOUT_SECONDS = 30.0
_ESTIMATE_RECEIPT_TTL_SECONDS = 900
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ProvidersOutput(BaseModel):
    providers: list[ProviderCapabilities]

    model_config = ConfigDict(extra="forbid")


class EstimateOutput(BaseModel):
    estimate: GenerationEstimate
    estimate_receipt: str
    receipt_expires_at: datetime

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class _Connection:
    base_url: str
    token: str
    project_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class _Receipt:
    project_id: uuid.UUID
    request_digest: str
    expires_monotonic: float


_estimate_receipts: dict[str, _Receipt] = {}


def _connection() -> _Connection:
    raw_url = os.environ.get("SOVA_MCP_API_URL", _DEFAULT_API_URL).strip()
    token = os.environ.get("SOVA_MCP_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SOVA_MCP_TOKEN is required")

    raw_projects = os.environ.get("SOVA_MCP_PROJECT_IDS", "").strip()
    if not raw_projects:
        raise RuntimeError("SOVA_MCP_PROJECT_IDS is required")
    try:
        project_ids = frozenset(uuid.UUID(value.strip()) for value in raw_projects.split(","))
    except ValueError as exc:
        raise RuntimeError("SOVA_MCP_PROJECT_IDS must be comma-separated UUIDs") from exc
    if not project_ids:
        raise RuntimeError("SOVA_MCP_PROJECT_IDS must contain at least one project")

    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("SOVA_MCP_API_URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("SOVA_MCP_API_URL must not contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise RuntimeError("SOVA_MCP_API_URL requires HTTPS outside loopback")

    path = parsed.path.rstrip("/") + "/"
    base_url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    return _Connection(base_url=base_url, token=token, project_ids=project_ids)


def _require_project(project_id: uuid.UUID) -> None:
    if project_id not in _connection().project_ids:
        raise ToolError("Project is outside the MCP allowlist")


async def _api_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    connection = _connection()
    url = urljoin(connection.base_url, path.lstrip("/"))
    request_headers = {
        **(headers or {}),
        "Authorization": f"Bearer {connection.token}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            async with client.stream(method, url, json=body, headers=request_headers) as response:
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > _MAX_RESPONSE_BYTES:
                            raise ToolError("Sova API response exceeded the MCP size limit")
                    except ValueError as exc:
                        raise ToolError("Sova API returned an invalid Content-Length") from exc
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise ToolError("Sova API response exceeded the MCP size limit")
                status_code = response.status_code
    except ToolError:
        raise
    except httpx.HTTPError as exc:
        raise ToolError("Sova API request failed") from exc

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("Sova API returned invalid JSON") from exc
    if status_code >= 400:
        detail = f"HTTP {status_code}"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                if isinstance(code, str) and isinstance(message, str):
                    detail = f"{detail} {code}: {message}"
            elif isinstance(payload.get("detail"), str):
                detail = f"{detail}: {payload['detail']}"
        detail = detail.replace(connection.token, "[redacted]")[:600]
        raise ToolError(f"Sova API rejected the request: {detail}")
    return payload


def _request_digest(request: GenerationRequest) -> str:
    canonical = request.model_dump_json(exclude_none=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _issue_receipt(project_id: uuid.UUID, request: GenerationRequest) -> tuple[str, datetime]:
    now = time.monotonic()
    expired = [
        key for key, receipt in _estimate_receipts.items() if receipt.expires_monotonic <= now
    ]
    for key in expired:
        del _estimate_receipts[key]
    value = secrets.token_urlsafe(32)
    _estimate_receipts[value] = _Receipt(
        project_id=project_id,
        request_digest=_request_digest(request),
        expires_monotonic=now + _ESTIMATE_RECEIPT_TTL_SECONDS,
    )
    return value, datetime.now(UTC) + timedelta(seconds=_ESTIMATE_RECEIPT_TTL_SECONDS)


def _consume_receipt(value: str, project_id: uuid.UUID, request: GenerationRequest) -> None:
    receipt = _estimate_receipts.get(value)
    if receipt is None or receipt.expires_monotonic <= time.monotonic():
        _estimate_receipts.pop(value, None)
        raise ToolError("estimate_receipt is missing or expired; call sova3d.estimate again")
    if receipt.project_id != project_id or receipt.request_digest != _request_digest(request):
        raise ToolError("estimate_receipt does not match this project and request")
    # There is no await above: one event-loop turn validates and consumes atomically. An
    # ambiguous HTTP outcome intentionally leaves the receipt consumed; API idempotency is the
    # only safe retry mechanism after a generation-start attempt.
    del _estimate_receipts[value]


mcp = MCPServer(
    name="Sova 3D",
    instructions=(
        "Use sova3d.estimate before sova3d.generate. Generation requires the matching, "
        "short-lived estimate receipt, caller confirmation, and an idempotency key. Tools "
        "expose no direct storage, deletion, or arbitrary code execution."
    ),
)


@mcp.tool(name="sova3d.providers")
async def providers() -> ProvidersOutput:
    """List currently enabled provider-neutral 3D capabilities."""

    payload = await _api_request("GET", "3d-generation/providers")
    return ProvidersOutput(providers=payload)


@mcp.tool(name="sova3d.estimate")
async def estimate(project_id: uuid.UUID, request: GenerationRequest) -> EstimateOutput:
    """Estimate cost and latency and issue a request-bound receipt valid for 15 minutes."""

    _require_project(project_id)
    payload = await _api_request(
        "POST",
        f"projects/{project_id}/3d-generations/estimate",
        body=request.model_dump(mode="json"),
    )
    estimate_value = GenerationEstimate.model_validate(payload)
    receipt, expires_at = _issue_receipt(project_id, request)
    return EstimateOutput(
        estimate=estimate_value,
        estimate_receipt=receipt,
        receipt_expires_at=expires_at,
    )


@mcp.tool(name="sova3d.generate")
async def generate(
    project_id: uuid.UUID,
    request: GenerationRequest,
    idempotency_key: str,
    estimate_receipt: str,
    confirmed_estimate: bool,
) -> JobAccepted:
    """Start a durable generation using the matching estimate receipt."""

    _require_project(project_id)
    if not confirmed_estimate:
        raise ToolError("confirmed_estimate must be true after reviewing sova3d.estimate")
    if not 1 <= len(idempotency_key) <= 128 or idempotency_key.strip() != idempotency_key:
        raise ToolError("idempotency_key must contain 1-128 non-padded characters")
    _consume_receipt(estimate_receipt, project_id, request)
    payload = await _api_request(
        "POST",
        f"projects/{project_id}/3d-generations",
        body=request.model_dump(mode="json"),
        headers={"Idempotency-Key": idempotency_key},
    )
    return JobAccepted.model_validate(payload)


@mcp.tool(name="sova3d.get_job")
async def get_job(project_id: uuid.UUID, job_id: uuid.UUID) -> ThreeDGenerationOut:
    """Read normalized progress and result metadata for one allowlisted project job."""

    _require_project(project_id)
    payload = await _api_request("GET", f"3d-generations/{job_id}")
    result = ThreeDGenerationOut.model_validate(payload)
    if result.project_id != project_id:
        raise ToolError("Generation job does not belong to the requested project")
    return result


@mcp.tool(name="sova3d.benchmark")
async def benchmark(project_id: uuid.UUID) -> GenerationBenchmarkReport:
    """Read allowlisted project provider/model quality, latency, cost, and outcomes."""

    _require_project(project_id)
    payload = await _api_request("GET", f"projects/{project_id}/3d-generations/benchmark")
    return GenerationBenchmarkReport.model_validate(payload)


def main() -> None:
    """Run the local MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()
