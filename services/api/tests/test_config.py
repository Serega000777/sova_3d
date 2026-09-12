import pytest
from pydantic import ValidationError

from app.config import load_settings


def test_settings_load_from_env() -> None:
    settings = load_settings()
    assert settings.app_env == "local"
    assert settings.s3_bucket == "test-bucket"
    assert settings.ai_provider == "stub"


def test_missing_required_env_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError) as exc_info:
        load_settings()
    assert "database_url" in str(exc_info.value)


def test_invalid_dsn_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "not-a-url")
    with pytest.raises(ValidationError):
        load_settings()


def test_unknown_ai_provider_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    with pytest.raises(ValidationError):
        load_settings()
