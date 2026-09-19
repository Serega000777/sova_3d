"""Environment schema. Missing/invalid required values fail at import time (T-005)."""

from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "dev", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint: str = Field(min_length=1)
    # Endpoint clients can reach for presigned URLs (SigV4 binds the host). Defaults to s3_endpoint.
    s3_public_endpoint: str | None = None
    s3_bucket: str = Field(min_length=1)
    s3_access_key: str = Field(min_length=1)
    s3_secret_key: str = Field(min_length=1)
    s3_region: str = "us-east-1"

    # Browser clients (web, and Expo web) are served from another origin; list the
    # origins allowed to call the API. "*" is accepted for local dev only.
    # 3100 = web dev server; 8081/8100 = Expo dev server (Expo Go and expo web).
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:8100",
            "http://127.0.0.1:8100",
        ]
    )

    # Prometheus scrape token (T-097). Unset means the endpoint does not exist.
    metrics_token: str | None = None

    ai_provider: Literal["stub", "anthropic"] = "stub"
    ai_model: str = "claude-opus-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    anthropic_api_key: str | None = None  # the SDK also reads ANTHROPIC_API_KEY itself
    ai_budget_usd_per_job: float = Field(default=1.0, gt=0)
    # Default per-workspace monthly AI budget (T-047); workspaces can override it.
    ai_workspace_monthly_budget_usd: float = Field(default=20.0, gt=0)

    # Marketplace payments (F-004): `none` = free listings only, priced ones answer 402;
    # `stub` completes an order without charging — development and demos, never production.
    payments_provider: Literal["none", "stub"] = "none"

    @model_validator(mode="after")
    def _no_stub_payments_in_production(self) -> "Settings":
        if self.app_env == "production" and self.payments_provider == "stub":
            raise ValueError("PAYMENTS_PROVIDER=stub is not allowed in production")
        return self


def load_settings() -> Settings:
    # pydantic-settings reads required fields from the environment; the explicit
    # call keeps mypy strict happy without a per-field `# type: ignore`.
    return Settings.model_validate({})
