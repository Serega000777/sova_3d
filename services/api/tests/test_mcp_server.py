from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from app import mcp_server
from app.ai.three_d import GenerationEstimate, GenerationRequest


@pytest.fixture(autouse=True)
def mcp_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[uuid.UUID]:
    project_id = uuid.uuid4()
    monkeypatch.setenv("SOVA_MCP_TOKEN", "test-token")
    monkeypatch.setenv("SOVA_MCP_PROJECT_IDS", str(project_id))
    monkeypatch.setenv("SOVA_MCP_API_URL", "http://127.0.0.1:8000/api/v1")
    mcp_server._estimate_receipts.clear()
    yield project_id
    mcp_server._estimate_receipts.clear()


def _request(prompt: str = "A small owl figurine") -> dict[str, Any]:
    return {
        "mode": "text",
        "purpose": "draft",
        "prompt": prompt,
        "target_format": "glb",
    }


def _estimate_payload() -> dict[str, Any]:
    return {
        "provider": "local",
        "model": "test-model",
        "provider_version": "1",
        "credits": None,
        "cost_usd": None,
        "latency_seconds_min": 10,
        "latency_seconds_max": 20,
        "target_format": "glb",
        "assumptions": ["test"],
    }


def _tool_json(result: Any) -> Any:
    assert result.is_error is False
    assert len(result.content) == 1
    return json.loads(cast(Any, result.content[0]).text)


@pytest.mark.asyncio
async def test_mcp_lists_only_typed_safe_generation_tools() -> None:
    async with Client(mcp_server.mcp) as client:
        result = await client.list_tools()

    assert [tool.name for tool in result.tools] == [
        "sova3d.providers",
        "sova3d.estimate",
        "sova3d.generate",
        "sova3d.get_job",
        "sova3d.benchmark",
    ]
    assert all(tool.output_schema is not None for tool in result.tools)
    exposed_schemas = json.dumps(
        [tool.input_schema for tool in result.tools], sort_keys=True
    ).lower()
    assert "token" not in exposed_schemas
    assert "api_url" not in exposed_schemas
    assert "project_ids" not in exposed_schemas


@pytest.mark.asyncio
async def test_estimate_issues_request_bound_receipt(
    monkeypatch: pytest.MonkeyPatch, mcp_environment: uuid.UUID
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_request(
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert headers is None
        calls.append((method, path, body or {}))
        return _estimate_payload()

    monkeypatch.setattr(mcp_server, "_api_request", fake_request)
    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "sova3d.estimate",
            {"project_id": str(mcp_environment), "request": _request()},
        )

    payload = _tool_json(result)
    receipt = payload["estimate_receipt"]
    assert payload["estimate"]["provider"] == "local"
    assert receipt in mcp_server._estimate_receipts
    assert calls[0][0:2] == (
        "POST",
        f"projects/{mcp_environment}/3d-generations/estimate",
    )
    assert calls[0][2]["prompt"] == "A small owl figurine"


@pytest.mark.asyncio
async def test_generate_requires_matching_one_use_receipt(
    monkeypatch: pytest.MonkeyPatch, mcp_environment: uuid.UUID
) -> None:
    request = GenerationRequest.model_validate(_request())
    receipt, _ = mcp_server._issue_receipt(mcp_environment, request)
    observed: dict[str, Any] = {}

    async def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        observed.update(method=method, path=path, **kwargs)
        return {"job_id": str(uuid.uuid4()), "status": "queued", "type": "generate_3d"}

    monkeypatch.setattr(mcp_server, "_api_request", fake_request)
    result = await mcp_server.generate(
        mcp_environment,
        request,
        "generation-1",
        receipt,
        True,
    )

    assert result.status == "queued"
    assert observed["headers"] == {"Idempotency-Key": "generation-1"}
    assert receipt not in mcp_server._estimate_receipts
    with pytest.raises(ToolError, match="missing or expired"):
        await mcp_server.generate(
            mcp_environment,
            request,
            "generation-1",
            receipt,
            True,
        )


@pytest.mark.asyncio
async def test_generate_rejects_changed_request_and_unconfirmed_estimate(
    mcp_environment: uuid.UUID,
) -> None:
    original = GenerationRequest.model_validate(_request())
    changed = GenerationRequest.model_validate(_request("A different object"))
    receipt, _ = mcp_server._issue_receipt(mcp_environment, original)

    with pytest.raises(ToolError, match="must be true"):
        await mcp_server.generate(mcp_environment, original, "generation-1", receipt, False)
    with pytest.raises(ToolError, match="does not match"):
        await mcp_server.generate(mcp_environment, changed, "generation-1", receipt, True)


def test_expired_receipt_is_rejected(mcp_environment: uuid.UUID) -> None:
    request = GenerationRequest.model_validate(_request())
    receipt = "expired"
    mcp_server._estimate_receipts[receipt] = mcp_server._Receipt(
        project_id=mcp_environment,
        request_digest=mcp_server._request_digest(request),
        expires_monotonic=time.monotonic() - 1,
    )

    with pytest.raises(ToolError, match="missing or expired"):
        mcp_server._consume_receipt(receipt, mcp_environment, request)
    assert receipt not in mcp_server._estimate_receipts


@pytest.mark.asyncio
async def test_receipt_is_consumed_before_concurrent_http_call(
    monkeypatch: pytest.MonkeyPatch, mcp_environment: uuid.UUID
) -> None:
    request = GenerationRequest.model_validate(_request())
    receipt, _ = mcp_server._issue_receipt(mcp_environment, request)
    entered_http = asyncio.Event()
    release_http = asyncio.Event()

    async def slow_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        entered_http.set()
        await release_http.wait()
        return {"job_id": str(uuid.uuid4()), "status": "queued", "type": "generate_3d"}

    monkeypatch.setattr(mcp_server, "_api_request", slow_request)
    first = asyncio.create_task(
        mcp_server.generate(mcp_environment, request, "generation-1", receipt, True)
    )
    await entered_http.wait()
    with pytest.raises(ToolError, match="missing or expired"):
        await mcp_server.generate(mcp_environment, request, "generation-2", receipt, True)
    release_http.set()
    await first


@pytest.mark.asyncio
async def test_receipt_stays_consumed_after_ambiguous_transport_failure(
    monkeypatch: pytest.MonkeyPatch, mcp_environment: uuid.UUID
) -> None:
    request = GenerationRequest.model_validate(_request())
    receipt, _ = mcp_server._issue_receipt(mcp_environment, request)

    async def failed_request(*args: Any, **kwargs: Any) -> Any:
        raise ToolError("Sova API request failed")

    monkeypatch.setattr(mcp_server, "_api_request", failed_request)
    with pytest.raises(ToolError, match="request failed"):
        await mcp_server.generate(mcp_environment, request, "generation-1", receipt, True)
    assert receipt not in mcp_server._estimate_receipts
    with pytest.raises(ToolError, match="missing or expired"):
        await mcp_server.generate(mcp_environment, request, "generation-1", receipt, True)


@pytest.mark.asyncio
async def test_project_allowlist_blocks_request_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_request(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return _estimate_payload()

    monkeypatch.setattr(mcp_server, "_api_request", fake_request)
    with pytest.raises(ToolError, match="outside the MCP allowlist"):
        await mcp_server.estimate(uuid.uuid4(), GenerationRequest.model_validate(_request()))
    assert called is False


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/api/v1",
        "ftp://127.0.0.1/api/v1",
        "https://user:pass@example.com/api/v1",
        "https://example.com/api/v1?token=secret",
        "https://example.com/api/v1#fragment",
    ],
)
def test_connection_rejects_unsafe_api_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("SOVA_MCP_API_URL", url)

    with pytest.raises(RuntimeError):
        mcp_server._connection()


def test_connection_requires_token_and_project_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOVA_MCP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SOVA_MCP_TOKEN is required"):
        mcp_server._connection()

    monkeypatch.setenv("SOVA_MCP_TOKEN", "test-token")
    monkeypatch.delenv("SOVA_MCP_PROJECT_IDS", raising=False)
    with pytest.raises(RuntimeError, match="SOVA_MCP_PROJECT_IDS is required"):
        mcp_server._connection()

    monkeypatch.setenv("SOVA_MCP_PROJECT_IDS", "not-a-uuid")
    with pytest.raises(RuntimeError, match="comma-separated UUIDs"):
        mcp_server._connection()


class _OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"a" * mcp_server._MAX_RESPONSE_BYTES
        yield b"b"


@pytest.mark.asyncio
async def test_api_response_stream_aborts_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_OversizedStream(), request=request)

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.mcp_server.httpx.AsyncClient", fake_client)
    with pytest.raises(ToolError, match="size limit"):
        await mcp_server._api_request("GET", "test")


@pytest.mark.asyncio
async def test_api_error_envelope_is_actionable_and_redacts_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "secret-api-token"
    monkeypatch.setenv("SOVA_MCP_TOKEN", token)
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            request=request,
            json={
                "error": {
                    "code": "idempotency_conflict",
                    "message": f"conflict reflected {token}",
                    "details": None,
                    "trace_id": "trace-1",
                }
            },
        )

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.mcp_server.httpx.AsyncClient", fake_client)
    with pytest.raises(ToolError) as exc_info:
        await mcp_server._api_request("GET", "test")

    message = str(exc_info.value)
    assert token not in message
    assert "[redacted]" in message
    assert "idempotency_conflict" in message


def test_models_preserve_decimal_cost() -> None:
    estimate = GenerationEstimate.model_validate({**_estimate_payload(), "cost_usd": "1.2500"})
    assert estimate.cost_usd == Decimal("1.2500")
