"""Provider connections and their synced state.

Credentials used to live in `.env`, which meant every key rotation was a
deploy and every environment drifted. They live here instead: encrypted,
editable by an authorised admin, and auditable -- who changed which key, and
when.

The plaintext never leaves this table except through `app.core.crypto.decrypt`
at the moment an adapter builds a client. No schema, API response, log line or
export carries it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import MoneyAmount, MoneyRate
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class ProviderKind(enum.StrEnum):
    """What a provider does. Routing and cost allocation both key off this."""

    TELEPHONY = "telephony"
    MESSAGING = "messaging"
    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    PAYMENTS = "payments"
    STORAGE = "storage"


class ProviderStatus(enum.StrEnum):
    #: Configured and its last health check passed.
    HEALTHY = "healthy"
    #: Credentials present but the last check failed.
    DEGRADED = "degraded"
    #: Enabled with no usable credentials. Refuses work rather than pretending.
    UNCONFIGURED = "unconfigured"
    DISABLED = "disabled"


class ProviderConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One configured account with one vendor.

    Scoped to an organization only for a tenant bringing their own account;
    a NULL organization_id is the platform's own connection, which is what
    almost every tenant uses.
    """

    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("slug", "organization_id", name="uq_provider_slug_org"),
        Index("ix_provider_kind_enabled", "kind", "is_enabled"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: "twilio", "anthropic", "deepgram". Matches the adapter's name.
    slug: Mapped[str] = mapped_column(String(48), index=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ProviderKind] = mapped_column(StrEnumType(ProviderKind, 24))
    environment: Mapped[str] = mapped_column(String(16), default="live")

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Lower wins. Lets an admin fail traffic over to a second carrier.
    priority: Mapped[int] = mapped_column(Integer, default=100)

    #: {"account_sid": "<fernet>", ...}. Encrypted individually so one key can
    #: be rotated without re-entering the rest.
    secrets: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Masked tails for display: {"account_sid": "••••1234"}. Safe to serve.
    secret_hints: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Non-secret settings: region, caller id, webhook url, subaccount.
    config: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[ProviderStatus] = mapped_column(
        StrEnumType(ProviderStatus, 16), default=ProviderStatus.UNCONFIGURED
    )
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Who last touched the credentials, for the audit trail.
    secrets_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    secrets_rotated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.secrets) and self.is_enabled


class ProviderBalance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A balance as the provider reported it, at a point in time.

    Kept as a series rather than a single mutable column so "we ran out at
    2am" is answerable afterwards. The currency is the provider's own -- a
    Twilio account can be denominated in USD while we invoice in it too, but
    that is a coincidence, not a guarantee.
    """

    __tablename__ = "provider_balances"
    __table_args__ = (Index("ix_provider_balance_time", "connection_id", "observed_at"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="CASCADE"), index=True
    )
    balance = mapped_column(MoneyAmount, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    #: Spend inside the provider's own billing period, when it reports one.
    period_spend = mapped_column(MoneyAmount, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProviderUsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A usage line as the provider itself reports it.

    This is the reconciliation side of the books: what Twilio says we used,
    against what our own call records say. A difference means we are either
    losing money to usage we never attributed, or billing for calls the
    carrier has no record of.

    Twilio nests usage categories (`calls` contains `calls-outbound`), so
    `is_parent` is stored and parents are excluded from sums. Adding them
    would double-count every minute.
    """

    __tablename__ = "provider_usage_records"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "category",
            "period_start",
            "period_end",
            name="uq_provider_usage_period",
        ),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: True for a rollup row whose children are also stored. Never summed.
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_category: Mapped[str | None] = mapped_column(String(120), nullable=True)

    quantity = mapped_column(MoneyRate, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost = mapped_column(MoneyAmount, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    #: Converted at the rate in force when synced, kept beside the original.
    cost_usd = mapped_column(MoneyAmount, nullable=True)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProviderSyncRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a background sync. Makes a stalled job visible."""

    __tablename__ = "provider_sync_runs"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
