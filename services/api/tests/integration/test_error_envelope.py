"""Every response, a crash included, carries the error envelope and the trace id (docs/03 §1)."""

from fastapi.testclient import TestClient
from httpx2 import Response

from app.main import create_app
from app.storage import S3Storage
from tests.integration.conftest import test_s3_settings as make_settings


def test_unhandled_error_is_an_envelope_the_browser_can_read(
    database_url: str, storage: S3Storage
) -> None:
    app = create_app(make_settings(database_url), storage=storage)

    @app.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response: Response = client.get(
            "/api/v1/_boom", headers={"Origin": "http://localhost:3100"}
        )

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["trace_id"] == response.headers["x-request-id"]
    # The client learns the trace id, never the internals.
    assert "secret internal detail" not in response.text
    # Without this header a browser sees an opaque network failure instead of the envelope.
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"


def test_a_model_validator_refusal_is_a_422_not_a_crash(
    database_url: str, storage: S3Storage
) -> None:
    from pydantic import BaseModel, model_validator

    class Body(BaseModel):
        a: int
        b: int

        @model_validator(mode="after")
        def ordered(self) -> "Body":
            if self.a > self.b:
                raise ValueError("a must not exceed b")
            return self

    app = create_app(make_settings(database_url), storage=storage)

    @app.post("/api/v1/_ordered")
    def ordered(body: Body) -> dict[str, int]:
        return {"a": body.a}

    with TestClient(app, raise_server_exceptions=False) as client:
        response: Response = client.post("/api/v1/_ordered", json={"a": 2, "b": 1})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "a must not exceed b" in str(error["details"])
