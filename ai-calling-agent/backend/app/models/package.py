"""Credit packages, and the orders that buy them.

Money is stored in integer minor units -- paise for INR, cents for USD -- never
as a float. 0.1 + 0.2 != 0.3 in binary floating point, and a rounding error in
a price is a rounding error in someone's bill.

A purchase snapshots the package it bought. Editing a package afterwards must
never change what a past customer paid or how many credits they received, so
the order carries its own copy of the terms rather than a pointer to live ones.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class PackageKind(enum.StrEnum):
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"
    PROMOTIONAL = "promotional"
    #: Negotiated terms for one customer; never shown on the public page.
    CUSTOM = "custom"


class OrderStatus(enum.StrEnum):
    """Our own lifecycle. Each provider's states are mapped onto these."""

    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    DISPUTED = "disputed"


class CreditPackage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a customer can buy. Prices here are the *current* ones."""

    __tablename__ = "credit_packages"
    __table_args__ = (UniqueConstraint("slug", name="uq_credit_packages_slug"),)

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[PackageKind] = mapped_column(
        StrEnumType(PackageKind, 16), default=PackageKind.ONE_TIME
    )

    #: Minor units: 99900 == ₹999.00. Integer so arithmetic is exact.
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    #: Tax in basis points: 1800 == 18% GST. Basis points avoid a float rate.
    tax_bps: Mapped[int] = mapped_column(Integer, default=0)

    base_credits: Mapped[int] = mapped_column(Integer)
    bonus_credits: Mapped[int] = mapped_column(Integer, default=0)

    #: Null means the credits never expire.
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Hidden packages are purchasable by direct link but not listed.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    max_per_organization: Mapped[int | None] = mapped_column(Integer, nullable=True)

    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def total_credits(self) -> int:
        return self.base_credits + self.bonus_credits

    @property
    def tax_minor(self) -> int:
        """Tax on the listed price, rounded half-up in minor units."""
        return (self.price_minor * self.tax_bps + 5000) // 10000

    @property
    def payable_minor(self) -> int:
        return self.price_minor + self.tax_minor


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One purchase attempt, carrying its own copy of the terms.

    The snapshot columns are deliberate duplication: a price change must not
    rewrite history, and an invoice issued last year must still reconcile.
    """

    __tablename__ = "orders"
    __table_args__ = (
        # One provider order maps to exactly one of ours, so a replayed
        # webhook cannot create a second purchase.
        UniqueConstraint("provider_order_id", name="uq_orders_provider_order_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        # Never delete a package a real order points at.
        ForeignKey("credit_packages.id", ondelete="RESTRICT"),
        nullable=True,
    )

    #: Human-facing reference, shown on invoices and in support conversations.
    reference: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        StrEnumType(OrderStatus, 20), default=OrderStatus.CREATED, index=True
    )

    # --- the snapshot ---------------------------------------------------
    package_name: Mapped[str] = mapped_column(String(120))
    price_minor: Mapped[int] = mapped_column(Integer)
    tax_minor: Mapped[int] = mapped_column(Integer, default=0)
    total_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    base_credits: Mapped[int] = mapped_column(Integer)
    bonus_credits: Mapped[int] = mapped_column(Integer, default=0)
    total_credits: Mapped[int] = mapped_column(Integer)
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- provider -------------------------------------------------------
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    #: Set once credits are allocated, so a replayed confirmation is a no-op.
    credits_allocated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_minor: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def is_paid(self) -> bool:
        return self.status is OrderStatus.PAID

    @property
    def refundable_minor(self) -> int:
        """What is still refundable. Never more than was actually paid."""
        return max(0, self.total_minor - self.refunded_minor)


class PaymentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every webhook the provider sent us, stored before it is acted on.

    Kept so "the webhook never arrived" is an answerable claim, and so a
    replayed delivery can be recognised rather than processed twice.
    """

    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
    )

    provider: Mapped[str] = mapped_column(String(32), index=True)
    #: The provider's own event id. The uniqueness constraint above is what
    #: makes replay protection a database guarantee rather than a code path.
    event_id: Mapped[str] = mapped_column(String(160), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
