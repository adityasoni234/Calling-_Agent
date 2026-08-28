from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class CampaignStatus(enum.StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class CampaignLeadStatus(enum.StrEnum):
    PENDING = "pending"
    DIALING = "dialing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXHAUSTED = "exhausted"
    SKIPPED = "skipped"


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[CampaignStatus] = mapped_column(
        StrEnumType(CampaignStatus, 16), default=CampaignStatus.DRAFT
    )

    # Calling windows are a legal requirement in India, not a nicety.
    calling_hours_start: Mapped[time] = mapped_column(Time, default=time(10, 0))
    calling_hours_end: Mapped[time] = mapped_column(Time, default=time(19, 0))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")

    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=2)
    delay_between_calls_seconds: Mapped[int] = mapped_column(Integer, default=5)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    retry_delay_minutes: Mapped[int] = mapped_column(Integer, default=180)
    budget_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignLead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "campaign_leads"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CampaignLeadStatus] = mapped_column(
        StrEnumType(CampaignLeadStatus, 16), default=CampaignLeadStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
