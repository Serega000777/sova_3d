"""Browser clients (web on :3100, Expo web) call the API cross-origin (T-087)."""

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.integration.conftest import Actor


def test_preflight_allows_the_configured_origin(api_client: TestClient) -> None:
    response: Response = api_client.options(
        "/api/v1/projects",
        headers={
            "Origin": "http://localhost:3100",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "idempotency-key" in allowed


def test_preflight_rejects_an_unknown_origin(api_client: TestClient) -> None:
    response: Response = api_client.options(
        "/api/v1/projects",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_actual_request_carries_the_origin_header(api_client: TestClient, actor: Actor) -> None:
    response: Response = api_client.get(
        "/api/v1/projects",
        params={"workspace_id": str(actor.workspace.id)},
        headers={**actor.headers, "Origin": "http://localhost:3100"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"
    # The trace id has to survive the cross-origin hop for clients to log it.
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
