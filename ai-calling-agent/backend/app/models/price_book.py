"""Versioned pricing.

Two rules shape this file.

**Published prices are immutable.** Editing a live rule would change what a
call last March cost, so publishing creates a new version and the old one
stays readable. A charge records the `price_rule_id` it was computed from.

**The rule carries its own arithmetic.** Voice bills per rounded-up minute,
SMS per segment, AI per thousand tokens, payments as a percentage plus a fixed
fee. Expressing those as separate code paths put pricing logic in five places
that drifted; here the row says which shape it is.
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import MoneyAmount, MoneyRate
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class Billable(enum.StrEnum):
    """What is being charged for. One rule per billable per price book."""

    VOICE_OUTBOUND = "voice_outbound"
    VOICE_INBOUND = "voice_inbound"
    SMS_OUTBOUND = "sms_outbound"
    SMS_INBOUND = "sms_inbound"
    WHATSAPP_OUTBOUND = "whatsapp_outbound"
    WHATSAPP_INBOUND = "whatsapp_inbound"
    WHATSAPP_TEMPLATE = "whatsapp_template"
    RECORDING = "recording"
    STORAGE = "storage"
    TRANSCRIPTION = "transcription"
    AI_TOKENS = "ai_tokens"
    PLATFORM_FEE = "platform_fee"
    PAYMENT_FEE = "payment_fee"


class RateKind(enum.StrEnum):
    PER_MINUTE = "per_minute"
    PER_UNIT = "per_unit"
    FLAT = "flat"
    #: Multiplier on measured provider cost. Self-correcting across carriers.
    COST_MARKUP = "cost_markup"
    PERCENT = "percent"
    TIERED = "tiered"


class Rounding(enum.StrEnum):
    #: Carriers bill a partial minute as a whole one; matching them protects
    #: the margin on short calls, which are most calls.
    UP_TO_INCREMENT = "up_to_increment"
    PER_SECOND = "per_second"
    NONE = "none"


class PriceBookStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PriceBook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, versioned set of prices.

    A NULL organization_id is a plan available to everyone; a set one is a
    negotiated book for a single customer.
    """

    __tablename__ = "price_books"
    __table_args__ = (
        UniqueConstraint("slug", "version", name="uq_price_book_slug_version"),
        Index("ix_price_book_active", "status", "effective_from"),
    )

    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[PriceBookStatus] = mapped_column(
        StrEnumType(PriceBookStatus, 16), default=PriceBookStatus.DRAFT
    )
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: The book new sign-ups get. Exactly one should carry it.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Required when publishing a rule that prices below known provider cost.
    #: Selling at a loss should be a decision someone signed, not an accident.
    below_cost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One line of a price book."""

    __tablename__ = "price_rules"
    __table_args__ = (
        UniqueConstraint(
            "price_book_id", "billable", "region", name="uq_price_rule_billable_region"
        ),
    )

    price_book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("price_books.id", ondelete="CASCADE"), index=True
    )
    billable: Mapped[Billable] = mapped_column(StrEnumType(Billable, 32), index=True)
    #: ISO country for destination-specific pricing. NULL is the fallback.
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)

    rate_kind: Mapped[RateKind] = mapped_column(StrEnumType(RateKind, 16))
    #: Price per unit/minute, the multiplier for COST_MARKUP, or the
    #: percentage for PERCENT. Eight places: AI tokens are priced in
    #: millionths and rounding here would make them free.
    rate = mapped_column(MoneyRate, nullable=False)
    #: Added on top of a per-unit or percentage charge, e.g. a gateway's
    #: "2.9% + $0.30".
    fixed_fee = mapped_column(MoneyAmount, nullable=True)
    #: Charged even when the computed amount is lower. A connected call that
    #: lasted two seconds still cost us a whole carrier minute.
    minimum_charge = mapped_column(MoneyAmount, nullable=True)

    rounding: Mapped[Rounding] = mapped_column(
        StrEnumType(Rounding, 24), default=Rounding.UP_TO_INCREMENT
    )
    increment_seconds: Mapped[int] = mapped_column(Integer, default=60)
    #: [{"up_to": 1000, "rate": "0.13"}, ...] for TIERED.
    tiers: Mapped[list] = mapped_column(JSONColumn(), default=list)

    #: What we believe this costs us, recorded when the rule was written. Lets
    #: the publish guard compare price against cost without a live lookup, and
    #: makes a stale assumption visible later.
    assumed_cost = mapped_column(MoneyRate, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single negotiated price for one customer.

    Separate from a whole custom price book, because the common case is one
    discounted line, and cloning a book for that leaves two to maintain.
    """

    __tablename__ = "price_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "billable", "region", name="uq_price_override_scope"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    billable: Mapped[Billable] = mapped_column(StrEnumType(Billable, 32))
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)
    rate_kind: Mapped[RateKind] = mapped_column(StrEnumType(RateKind, 16))
    rate = mapped_column(MoneyRate, nullable=False)
    minimum_charge = mapped_column(MoneyAmount, nullable=True)

    reason: Mapped[str] = mapped_column(Text)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
