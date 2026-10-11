"""Credits: what a customer buys, and what a call spends.

A ledger, not a mutable balance field. Every movement is a row, and the balance
is the sum of them -- so "where did my credits go" is always answerable, and a
bug can never silently make credits appear. The denormalised balance on the
organization is a cache for the hot path, rebuilt from the ledger.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class CreditEntryKind(enum.StrEnum):
    """Why credits moved. Signed amount, so the kind never contradicts it."""

    #: Platform granted credits -- a trial, goodwill, or a manual top-up.
    GRANT = "grant"
    #: Customer bought credits.
    PURCHASE = "purchase"
    #: A call consumed credits.
    USAGE = "usage"
    #: Credits returned for a call that failed and should not have been billed.
    REFUND = "refund"
    #: Platform correction, always with a note explaining it.
    ADJUSTMENT = "adjustment"
    #: Credits removed when a plan expires or an account is closed.
    EXPIRY = "expiry"


class PlanTier(enum.StrEnum):
    TRIAL = "trial"
    STARTER = "starter"
    GROWTH = "growth"
    SCALE = "scale"


class CreditEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One movement of credits. Append-only: corrections are new rows."""

    __tablename__ = "credit_entries"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[CreditEntryKind] = mapped_column(StrEnumType(CreditEntryKind, 16), index=True)
    #: Positive adds, negative spends. Never zero.
    amount: Mapped[float] = mapped_column(Float)
    #: Running balance immediately after this entry, so a statement can be read
    #: without re-summing the whole history.
    balance_after: Mapped[float] = mapped_column(Float)
    #: The order that produced these credits, when it is a purchase. Lets a
    #: payment be traced to the exact credits it granted.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: The call this usage belongs to, when it is usage.
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Who did it, for anything a human initiated.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What this cost us, for a usage entry. Margin is credits minus this.
    provider_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class PlatformEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit trail for platform-administrator actions.

    Anything an admin does to someone else's account is recorded. The first
    question after an incident is always "who did this", and a system that
    cannot answer it is not one you can let staff near.
    """

    __tablename__ = "platform_events"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
