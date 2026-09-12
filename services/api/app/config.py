"""Environment schema. Missing/invalid required values fail at import time (T-005)."""

from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "dev", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint: str = Field(min_length=1)
    s3_bucket: str = Field(min_length=1)
    s3_access_key: str = Field(min_length=1)
    s3_secret_key: str = Field(min_length=1)
    s3_region: str = "us-east-1"

    ai_provider: Literal["stub", "anthropic"] = "stub"
    ai_budget_usd_per_job: float = Field(default=1.0, gt=0)


def load_settings() -> Settings:
    # pydantic-settings reads required fields from the environment; the explicit
    # call keeps mypy strict happy without a per-field `# type: ignore`.
    return Settings.model_validate({})
