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

    # Image-to-3D for a phone photo scan (F-019): `stub` builds a placeholder stand-in;
    # `shap_e` runs a real (CPU-only, ~15-30 min) single-photo mesh reconstruction. A
    # dedicated scanner's fragments always use the `fusion` provider regardless of this.
    reconstruction_provider: Literal["stub", "shap_e"] = "stub"

    # Organic text-to-mesh (F-001/F-075): a figurine or a vase from a description, via
    # Shap-E's text model on CPU (~15-30 min per shape). `none` answers 501.
    mesh_generation_provider: Literal["none", "shap_e"] = "none"

    # Live project rooms (F-018): `memory` for one API instance, `redis` (pub/sub on REDIS_URL)
    # when several instances serve the same rooms.
    live_broker: Literal["memory", "redis"] = "memory"
    live_poll_seconds: float = Field(default=2.0, ge=0.05, le=30.0)

    # Marketplace payments (F-004): `none` = free listings only, priced ones answer 402;
    # `stub` completes an order without charging — development and demos, never production.
    payments_provider: Literal["none", "stub"] = "none"

    # Sign-in (F-083): one-time codes by SMS/email and OAuth accounts sit behind adapters.
    # `stub` shows the code in the response and answers OAuth with a demo consent page —
    # development and demos, never production. `none` switches the method off (501).
    signin_delivery: Literal["none", "stub"] = "stub"
    signin_oauth: Literal["none", "stub"] = "stub"
    signin_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    signin_session_days: int = Field(default=30, ge=1, le=365)
    signin_max_attempts: int = Field(default=5, ge=3, le=10)
    signin_codes_per_hour: int = Field(default=6, ge=1, le=100)  # per address

    @model_validator(mode="after")
    def _no_stubs_in_production(self) -> "Settings":
        if self.app_env == "production":
            if self.payments_provider == "stub":
                raise ValueError("PAYMENTS_PROVIDER=stub is not allowed in production")
            if self.signin_delivery == "stub" or self.signin_oauth == "stub":
                raise ValueError("SIGNIN_DELIVERY/SIGNIN_OAUTH=stub are not allowed in production")
        return self


def load_settings() -> Settings:
    # pydantic-settings reads required fields from the environment; the explicit
    # call keeps mypy strict happy without a per-field `# type: ignore`.
    return Settings.model_validate({})
