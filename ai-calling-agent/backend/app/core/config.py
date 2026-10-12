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
    #: Both dev servers: 5173 is the customer app, 5174 the admin panel.
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    #: Where the customer-facing app is served. Used to build the support
    #: handoff link, which must point at the customer app rather than the
    #: admin console. Defaults to the first CORS origin, which is the
    #: customer app by the convention above.
    app_base_url: str = ""

    # --- public reachability -------------------------------------------
    # The https URL telephony providers call back on. Required for real calls;
    # use an ngrok/cloudflared tunnel in development.
    public_base_url: str = "http://localhost:8000"

    # --- provider selection --------------------------------------------
    # Every one defaults to "mock": the whole pipeline runs end to end with no
    # vendor account, which is what makes it testable.
    telephony_provider: str = "mock"
    #: "mock" records sends without a carrier account, so the whole path runs
    #: locally and in tests. "twilio" uses real credentials.
    messaging_provider: str = "mock"
    #: "mailbox" (each customer connects their own Gmail or Outlook, the
    #: default), "mock", "smtp" or "postmark". Mailbox costs the platform
    #: nothing and sends from an address the recipient recognises.
    email_provider: str = "mailbox"

    # --- customer mailbox OAuth -----------------------------------------
    #: From console.cloud.google.com. The gmail.send scope needs Google
    #: verification before more than 100 users can connect.
    google_client_id: str = ""
    google_client_secret: str = ""
    #: From the Azure portal. Mail.Send needs no admin consent for personal
    #: accounts; a Workspace-equivalent tenant may require it.
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    # --- Meta lead ads --------------------------------------------------
    #: From developers.facebook.com. The secret also signs webhooks, so a
    #: wrong one shows up as every lead webhook being rejected.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    #: Echoed back during Meta's webhook verification handshake.
    meta_verify_token: str = ""

    # --- email delivery -------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    postmark_token: str = ""
    #: Where unsubscribe links point. Must be publicly reachable or the
    #: one-click header Gmail requires will not work.
    email_public_base_url: str = ""
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
    #: WhatsApp uses a separate sender from the voice caller id. Twilio's
    #: shared sandbox is +14155238886, which works once a recipient has
    #: joined it -- the realistic way to test before a business number is
    #: approved, which takes days.
    twilio_whatsapp_number: str = ""
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
    #: A call whose provider never sent a terminal webhook is written off after
    #: this long. Without it such calls count as "active" forever and silently
    #: consume the concurrency cap, which stops the dialler dead.
    stale_call_timeout_minutes: int = 30
    #: Largest lead CSV accepted by any upload endpoint.
    max_csv_bytes: int = 10 * 1024 * 1024
    #: Country code assumed for a number typed without one. Wrong here means a
    #: carrier silently dials the wrong country -- a bare Indian mobile handed
    #: to a US account is read as +1 and the call is refused.
    default_country_code: str = "+91"

    # --- commercial ----------------------------------------------------
    #: What a call sells for, as a multiple of what the providers charge us.
    #: A multiplier rather than a fixed per-minute price because telephony to
    #: the UK costs six times India -- one flat price would lose money on one
    #: region or be uncompetitive in the other.
    #: Gross margin dial. 3.0 means a call that costs us Rs10 is sold for Rs30.
    #: Cost-plus rather than a flat per-minute price, because telephony to the
    #: UK costs six times India and one flat price cannot serve both.
    credit_markup_multiplier: float = 3.0
    #: Provider invoices are in USD; we sell in INR. Without this the two were
    #: never reconciled and credits were sold at a tenth of their cost basis.
    #: Review it when the rate moves more than a few percent -- it is the one
    #: number that silently changes every margin on the platform.
    usd_inr_rate: float = 88.0
    #: Credits given to a brand-new organization so it can place a test call.
    #: About ten minutes of agent calling. Credits are 10 per rupee, so this
    #: is Rs300 of list price -- enough to judge the product before paying.
    trial_credits: float = 3000.0

    # --- payments ------------------------------------------------------
    #: Which provider to use. Anything unset leaves payments refusing clearly
    #: rather than pretending to work.
    payment_provider: str = "razorpay"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

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
    # How long a pause must be before the transcript is finalised. Higher means
    # fewer fragments and fewer interruptions, at the cost of a little latency.
    #: Fallback wait before replying to a FINAL that is not end-of-speech.
    #: Only reached when the provider has not endpointed yet, so lowering it
    #: trades dead air against answering a half-finished sentence.
    turn_debounce_seconds: float = 0.6
    stt_endpointing_ms: int = 300
    stt_utterance_end_ms: int = 1000
    tts_voice_id: str = ""
    tts_model: str = ""

    # --- conversation tuning -------------------------------------------
    # Audio format on the wire. Both Plivo and Twilio stream 8 kHz mu-law.
    audio_sample_rate: int = 8000
    audio_encoding: str = "mulaw"
    barge_in_enabled: bool = True
    # Barge-in tuning. The default was to cancel on the provider's VAD event
    # alone, which fires on a cough, room noise, or the agent's own echo -- so
    # the agent stopped talking constantly. These require evidence of actual
    # speech before interrupting.
    #
    # Words in a partial transcript before we accept it as a real interruption.
    barge_in_min_words: int = 2
    # Ignore interruptions in the first moments of an utterance: this is when
    # echo of the agent's own voice is most likely to come back.
    barge_in_grace_ms: int = 500
    # Inbound audio quieter than this is treated as room noise, not speech.
    barge_in_min_dbfs: float = -45.0
    # If an interruption produces no transcript within this window, the customer
    # did not actually speak -- resume rather than leaving dead air.
    barge_in_recover_ms: int = 1500
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
    def customer_app_url(self) -> str:
        if self.app_base_url:
            return self.app_base_url.rstrip("/")
        origins = self.cors_origin_list
        return origins[0].rstrip("/") if origins else "http://localhost:5173"

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
