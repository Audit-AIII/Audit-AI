"""Configuration loaded from the environment. See .env.example for the full list."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


MIN_AUTH_SECRET_CHARS = 32  # HS256 key: at least 256 bits of text


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
    # Trust Scorecard (GET /api/evaluations/latest): where the engine's evaluation runner writes
    # its timestamped reports. Defaults to services/verification/eval/reports in this repository.
    evaluation_reports_dir: str = str(
        Path(__file__).resolve().parents[3] / "verification" / "eval" / "reports"
    )
    # --- Security limits (services/verification/SECURITY.md, "Whole system") ---
    # JSON request bodies larger than this are refused (413) before they are read or parsed.
    # Upload routes get max_source_upload_bytes plus 1 MB for the multipart envelope instead.
    max_request_body_bytes: int = 1_000_000
    # Every SQL statement is cancelled after this long (PostgreSQL statement_timeout).
    db_statement_timeout_ms: int = 15_000
    # Per review: claims kept from the content, model calls (retries included), estimated
    # tokens, and wall-clock time. A review that hits a limit is marked for human review; nothing
    # beyond the limit is sent to a model (inkloom_verify.providers.budget).
    review_max_claims: int = 50
    review_max_llm_calls: int = 100
    review_max_estimated_tokens: int = 400_000
    review_deadline_seconds: float = 180.0

    def security_problems(self) -> list[str]:
        """Unsafe settings, by name only (values are never included)."""
        problems = []
        if len(self.auth_secret_key) < MIN_AUTH_SECRET_CHARS:
            problems.append(
                f"AUTH_SECRET_KEY is missing or shorter than {MIN_AUTH_SECRET_CHARS} characters"
            )
        if "*" in self.cors_origins:
            problems.append(
                "CORS_ALLOW_ORIGINS must list origins, not '*' (credentials are allowed)"
            )
        return problems

    def check_startup(self) -> list[str]:
        """Refuses to start in production with unsafe settings; returns them elsewhere (to warn)."""
        problems = self.security_problems()
        if problems and self.environment.lower() == "production":
            raise RuntimeError("insecure configuration: " + "; ".join(problems))
        return problems

    # Trust Scorecard (POST /api/evaluations): runs synchronously, bounded by the engine's own
    # call budget; at most one run per user per eval_min_interval_seconds.
    eval_max_calls: int = 150
    eval_deadline_seconds: float = 300.0
    eval_min_interval_seconds: float = 600.0
    # A run where more than this share of claims got no verdict (provider failures / budget) is
    # not stored: its numbers would describe the provider's outage, not the checker.
    eval_max_provider_failure_rate: float = 0.2
    # Override only for tests / a different labelled set; default is the engine's locked
    # services/verification/eval/dataset.jsonl.
    eval_dataset_path: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
