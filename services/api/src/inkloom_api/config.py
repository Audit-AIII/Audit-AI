"""Configuration loaded from the environment. See .env.example for the full list."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    auth_secret_key: str = ""
    auth_token_ttl_minutes: int = 60 * 12
    environment: str = "development"
    log_level: str = "INFO"
    cors_allow_origins: str = "http://localhost:3000"
    # Phase 4: brand source uploads. Never a public/static path - see .gitignore ("var/").
    brand_source_storage_dir: str = "var/brand_sources"
    max_source_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    # Phase 5 task 7: rate limits on review submissions. In-memory, single-process (documented
    # limitation - a multi-worker deployment would need a shared store; out of scope here).
    rate_limit_submissions_per_user: int = 20
    rate_limit_submissions_per_organisation: int = 100
    rate_limit_window_seconds: float = 60.0
    # Self-serve onboarding (POST /api/auth/register): keyed on request.client.host only - never
    # X-Forwarded-For, which an untrusted caller can set to anything.
    rate_limit_registrations_per_ip: int = 5
    rate_limit_registration_window_seconds: float = 600.0

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
