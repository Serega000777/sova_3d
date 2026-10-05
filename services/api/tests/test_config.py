from pathlib import Path

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


def test_prompt_example_bundle_path_and_digest_are_an_atomic_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROMPT_EXAMPLES_PATH", "/secure/examples.json")
    with pytest.raises(ValidationError, match="must be set together"):
        load_settings()
    monkeypatch.setenv("AI_PROMPT_EXAMPLES_SHA256", "not-a-digest")
    with pytest.raises(ValidationError, match="64 hexadecimal"):
        load_settings()
    monkeypatch.setenv("AI_PROMPT_EXAMPLES_SHA256", "a" * 64)
    assert load_settings().ai_prompt_examples_path == Path("/secure/examples.json")


def test_signin_stubs_are_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENTS_PROVIDER", "none")
    monkeypatch.setenv("SIGNIN_DELIVERY", "stub")
    with pytest.raises(ValidationError, match="SIGNIN"):
        load_settings()
    monkeypatch.setenv("SIGNIN_DELIVERY", "none")
    monkeypatch.setenv("SIGNIN_OAUTH", "none")
    monkeypatch.setenv("PRINTER_BRIDGE_PROVIDER", "none")
    assert load_settings().signin_delivery == "none"


def test_octoprint_requires_server_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_BRIDGE_PROVIDER", "octoprint")
    with pytest.raises(ValidationError, match="OCTOPRINT_URL"):
        load_settings()
    monkeypatch.setenv("OCTOPRINT_URL", "http://printer.lan")
    with pytest.raises(ValidationError, match="OCTOPRINT_API_KEY"):
        load_settings()
    monkeypatch.setenv("OCTOPRINT_API_KEY", "secret")
    assert load_settings().printer_bridge_provider == "octoprint"
