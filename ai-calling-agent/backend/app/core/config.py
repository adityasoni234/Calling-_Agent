"""Application settings.

Everything that differs between environments, and every secret, comes from the
environment. Nothing here has a production-safe default that would let the app
boot misconfigured in production without complaining -- see `_validate()`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env first, then backend/.env, which wins if both exist.
        # Skipped entirely under APP_ENV=test so the suite is hermetic: without
        # this, adding a key to a developer's .env silently changes test
        # behaviour (a webhook secret there once 403'd every webhook test).
        env_file=() if os.getenv("APP_ENV") == "test" else ("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---------------------------------------------------
    app_name: str = "AI Calling Agent"
    app_env: Environment = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- security ------------------------------------------------------
    secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    bcrypt_rounds: int = 12
    allow_registration: bool = True

    # --- persistence ---------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/calling_agent"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # --- http ----------------------------------------------------------
    # Kept as a raw string: pydantic-settings JSON-decodes list-typed fields
    # straight from the environment, before any validator can normalise them,
    # so a comma-separated CORS_ORIGINS would fail to parse. Read it through
    # `cors_origin_list`.
    cors_origins: str = "http://localhost:5173"

    # --- public reachability -------------------------------------------
    # The https URL telephony providers call back on. Required for real calls;
    # use an ngrok/cloudflared tunnel in development.
    public_base_url: str = "http://localhost:8000"

    # --- provider selection --------------------------------------------
    # Every one defaults to "mock": the whole pipeline runs end to end with no
    # vendor account, which is what makes it testable.
    telephony_provider: str = "mock"
    stt_provider: str = "mock"
    llm_provider: str = "mock"
    tts_provider: str = "mock"
    embedding_provider: str = "mock"

    # --- telephony credentials -----------------------------------------
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_caller_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_caller_id: str = ""
    telnyx_api_key: str = ""
    # The Call Control application the number is assigned to.
    telnyx_connection_id: str = ""
    telnyx_caller_id: str = ""
    # OmniDimension: hosted agent platform. Sells Indian numbers instantly,
    # but runs the conversation itself -- see its adapter docstring.
    omnidimension_api_key: str = ""
    omnidimension_agent_id: str = ""
    omnidimension_from_number_id: str = ""
    telephony_webhook_secret: str = ""
    # Agent that answers inbound calls. Blank falls back to the first active
    # agent, which is what a single-agent deployment wants.
    inbound_agent_id: str = ""
    # How long to let the destination ring before giving up.
    ring_timeout_seconds: int = 60

    # --- model providers -----------------------------------------------
    anthropic_api_key: str = ""
    # Required when the key is identity-linked: such keys must name the
    # workspace each request acts in, or the API rejects them with a 400.
    anthropic_workspace_id: str = ""
    openai_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""
    elevenlabs_api_key: str = ""
    sarvam_api_key: str = ""
    llm_base_url: str = ""

    llm_model: str = "claude-haiku-4-5"
    llm_max_tokens: int = 300
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    stt_model: str = "nova-2"
    stt_language: str = "multi"
    tts_voice_id: str = ""
    tts_model: str = ""

    # --- conversation tuning -------------------------------------------
    # Audio format on the wire. Both Plivo and Twilio stream 8 kHz mu-law.
    audio_sample_rate: int = 8000
    audio_encoding: str = "mulaw"
    barge_in_enabled: bool = True
    # Rolling-summary threshold: turns older than this are compressed instead of
    # resent verbatim, which is what keeps token cost linear in call length.
    context_max_turns: int = 12
    rag_top_k: int = 4
    rag_min_score: float = 0.25

    # --- campaigns / limits --------------------------------------------
    max_global_concurrent_calls: int = 10
    daily_budget_usd: float = 0.0
    monthly_budget_usd: float = 0.0
    upload_dir: str = "/app/uploads"
    max_upload_mb: int = 25

    # --- logging -------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.app_env == "production":
            if self.secret_key == "dev-only-insecure-secret-change-me":
                raise ValueError("SECRET_KEY must be set to a real secret in production")
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if "*" in self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must not be '*' in production")
            if self.telephony_provider != "mock" and not self.public_base_url.startswith(
                "https://"
            ):
                raise ValueError(
                    "PUBLIC_BASE_URL must be a public https URL in production: "
                    "carriers fetch answer documents and open the media socket from it"
                )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """Alembic runs its migrations through a sync driver."""
        return self.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
