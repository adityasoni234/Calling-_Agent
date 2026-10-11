"""Exchange rates, kept as history rather than a setting.

A conversion done today with today's rate must still be explainable next
year, so every converted amount stores the rate that produced it and this
table records where that rate came from. Re-converting an old charge at a new
rate would silently rewrite history, which is the thing an immutable ledger
exists to prevent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import MoneyRate
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExchangeRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One currency's value against USD, effective from a moment.

    USD is the base everywhere: provider invoices arrive in it, and the
    platform reports in it. `rate` is how many units of `currency` one USD
    buys, so INR sits at about 88.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("currency", "effective_from", name="uq_fx_currency_from"),
        Index("ix_fx_lookup", "currency", "effective_from"),
    )

    currency: Mapped[str] = mapped_column(String(8), index=True)
    #: Units of `currency` per 1 USD.
    rate = mapped_column(MoneyRate, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: Where it came from, so a wrong number is traceable to a wrong source.
    source: Mapped[str] = mapped_column(String(200), default="manual")
