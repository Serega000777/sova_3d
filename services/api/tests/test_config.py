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


def test_signin_stubs_are_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENTS_PROVIDER", "none")
    monkeypatch.setenv("SIGNIN_DELIVERY", "stub")
    with pytest.raises(ValidationError, match="SIGNIN"):
        load_settings()
    monkeypatch.setenv("SIGNIN_DELIVERY", "none")
    monkeypatch.setenv("SIGNIN_OAUTH", "none")
    assert load_settings().signin_delivery == "none"
