import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/test",
    "REDIS_URL": "redis://localhost:6379/1",
    "S3_ENDPOINT": "http://localhost:9000",
    "S3_BUCKET": "test-bucket",
    "S3_ACCESS_KEY": "test",
    "S3_SECRET_KEY": "test",
}


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def client() -> TestClient:
    """App wired to test settings; no DB/S3 traffic unless an endpoint touches them."""
    return TestClient(create_app(load_settings()))
