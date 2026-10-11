"""Credits held for a call in flight.

Credits used to be charged only once a call finished, so an account with ten
credits could start twenty concurrent calls and go arbitrarily negative -- the
balance check passed twenty times before any of them settled. A reservation is
taken before the phone rings and settled against real usage afterwards.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class ReservationStatus(enum.StrEnum):
    #: Credits are set aside and cannot be spent by another call.
    HELD = "held"
    #: The call finished; actual usage was charged and the rest released.
    SETTLED = "settled"
    #: The call never incurred usage, so everything went back.
    RELEASED = "released"
    #: No terminal event ever arrived and the reaper gave the credits back.
    EXPIRED = "expired"


class CreditReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One hold against an account, for one call.

    Unique on call_id: a retried origination must not stack two holds on the
    same call, which would silently double the amount a customer cannot spend.
    """

    __tablename__ = "credit_reservations"
    __table_args__ = (UniqueConstraint("call_id", name="uq_credit_reservations_call"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Credits held. Positive.
    amount: Mapped[float] = mapped_column(Float)
    #: What was actually charged when it settled. Null while held.
    settled_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ReservationStatus] = mapped_column(
        StrEnumType(ReservationStatus, 12), default=ReservationStatus.HELD, index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
