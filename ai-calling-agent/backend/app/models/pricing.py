from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PricingRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A rate you personally read off a vendor's rate card.

    `source_url` and `verified_at` are mandatory: an unattributed rate is how a
    cost model quietly becomes fiction. No rate ships with this repo.
    """

    __tablename__ = "pricing_rates"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    component: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str] = mapped_column(String(32))
    rate: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    # Optional destination scoping, e.g. "IN" for India termination.
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_url: Mapped[str] = mapped_column(String(600))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
