"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-only-change-me-dev-only-change-me"
_INSECURE_DEFAULT_PASSWORD = "admin"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general -----------------------------------------------------------
    app_name: str = "InsightForge"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    # Comma-separated list; empty means "same-origin only" (the nginx proxy serves UI + API).
    cors_origins: str = ""

    # --- elasticsearch -------------------------------------------------------
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_username: str | None = None
    elasticsearch_password: SecretStr | None = None
    elasticsearch_api_key: SecretStr | None = None
    elasticsearch_verify_certs: bool = True
    elasticsearch_ca_certs: str | None = None
    elasticsearch_request_timeout: float = 10.0
    elasticsearch_bootstrap_retries: int = 12
    index_prefix: str = "insightforge"
    index_replicas: int = 0  # single-node friendly; set to 1+ on a real cluster
    log_retention_days: int = Field(default=14, ge=1)
    rollover_max_age: str = "1d"
    rollover_max_primary_shard_size: str = "10gb"

    # --- ingestion -----------------------------------------------------------
    ingest_batch_size: int = Field(default=500, ge=1, le=10_000)
    ingest_flush_interval_seconds: float = Field(default=1.0, gt=0)
    ingest_queue_max_size: int = Field(default=50_000, ge=100)
    ingest_max_bulk_request_items: int = Field(default=1_000, ge=1)
    ingest_max_retries: int = Field(default=3, ge=0)

    # --- auth ----------------------------------------------------------------
    auth_enabled: bool = True
    jwt_secret: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60, ge=1)
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr(_INSECURE_DEFAULT_PASSWORD)
    viewer_username: str | None = None
    viewer_password: SecretStr | None = None
    # Comma-separated API keys accepted on the ingestion endpoints via the X-API-Key header.
    ingest_api_keys: SecretStr = SecretStr("")

    # --- alerting / notifications --------------------------------------------
    alert_sweep_interval_seconds: float = Field(default=15.0, gt=0)
    slack_webhook_url: SecretStr | None = None
    pagerduty_routing_key: SecretStr | None = None
    pagerduty_events_url: str = "https://events.pagerduty.com/v2/enqueue"
    alert_webhook_url: str | None = None
    alert_webhook_secret: SecretStr | None = None
    notification_timeout_seconds: float = 5.0
    public_dashboard_url: str = "http://localhost:3000"

    # --- live stream -----------------------------------------------------------
    stream_heartbeat_seconds: float = 15.0
    stream_subscriber_queue_size: int = 1_000

    @property
    def cors_origin_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def ingest_api_key_list(self) -> list[str]:
        return _split_csv(self.ingest_api_keys.get_secret_value())

    @property
    def logs_data_stream(self) -> str:
        return f"{self.index_prefix}-logs"

    @property
    def alerts_index(self) -> str:
        return f"{self.index_prefix}-alerts"

    @property
    def rules_index(self) -> str:
        return f"{self.index_prefix}-alert-rules"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _refuse_insecure_production_defaults(self) -> Settings:
        if not self.is_production or not self.auth_enabled:
            return self
        problems = []
        secret = self.jwt_secret.get_secret_value()
        if secret == _INSECURE_DEFAULT_SECRET or len(secret) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
        if self.admin_password.get_secret_value() == _INSECURE_DEFAULT_PASSWORD:
            problems.append("ADMIN_PASSWORD must be changed from the default")
        if not self.ingest_api_key_list:
            problems.append("INGEST_API_KEYS must contain at least one key")
        if problems:
            raise ValueError("Insecure production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
