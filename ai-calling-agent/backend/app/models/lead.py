from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class LeadStatus(enum.StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    QUALIFIED = "qualified"
    NOT_INTERESTED = "not_interested"
    CALLBACK = "callback"
    UNREACHABLE = "unreachable"
    DO_NOT_CALL = "do_not_call"
    CONVERTED = "converted"


class InterestLevel(enum.StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Stored E.164. Unique per organization, enforced in migration 0002.
    phone_number: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[LeadStatus] = mapped_column(
        StrEnumType(LeadStatus, 24), default=LeadStatus.NEW, index=True
    )
    interest_level: Mapped[InterestLevel] = mapped_column(
        StrEnumType(InterestLevel, 16), default=InterestLevel.UNKNOWN
    )
    lead_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONColumn(), default=dict)
