from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class CallStatus(enum.StrEnum):
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    CANCELED = "canceled"


TERMINAL_STATUSES = {
    CallStatus.COMPLETED,
    CallStatus.FAILED,
    CallStatus.NO_ANSWER,
    CallStatus.BUSY,
    CallStatus.CANCELED,
}


class CallDirection(enum.StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class UsageComponent(enum.StrEnum):
    TELEPHONY = "telephony"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    EMBEDDING = "embedding"
    INFRA = "infra"


class CallSource(enum.StrEnum):
    """How a call came to exist.

    Distinct from CallMode, which says who does the talking. A customer pressing
    "call" to launch an AI agent is MANUAL source with AGENT mode -- conflating
    the two makes it impossible to answer "who started this" after the fact.
    """

    #: A person clicked a button in the dashboard.
    MANUAL = "manual"
    #: A campaign's dispatcher placed it.
    CAMPAIGN = "campaign"
    #: An external system called us with an API key.
    API = "api"
    #: Someone rang our number.
    INBOUND = "inbound"
    #: A scheduled follow-up fired.
    SCHEDULED = "scheduled"
    #: Placed by platform staff or a test harness.
    INTERNAL = "internal"


class CallMode(enum.StrEnum):
    """Who does the talking.

    AGENT is the AI conversation. HUMAN is a bridged call: the platform rings
    the operator's own phone, then connects them to the lead -- so a person can
    work the same lead list without a separate dialler, and the call still gets
    a record, a recording and a cost line.
    """

    AGENT = "agent"
    HUMAN = "human"


class Call(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calls"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    #: Null on a human-operated call, which has no AI agent behind it.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    direction: Mapped[CallDirection] = mapped_column(
        StrEnumType(CallDirection, 12), default=CallDirection.OUTBOUND
    )
    mode: Mapped[CallMode] = mapped_column(
        StrEnumType(CallMode, 12), default=CallMode.AGENT, index=True
    )
    #: Which person started this. Null for campaign dispatch and inbound calls,
    #: which have no human initiator -- the campaign or route owns those.
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[CallSource] = mapped_column(
        StrEnumType(CallSource, 12), default=CallSource.MANUAL, index=True
    )
    #: Free-form provenance: the API key's name, the campaign's dispatch tick,
    #: the inbound number dialled. Enough to reconstruct the origin later.
    source_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: What the agent's configuration looked like when this call ran. An agent
    #: edited afterwards must not silently rewrite the history of its calls.
    agent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: On a human call, the operator's phone -- the leg we ring first.
    operator_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    from_number: Mapped[str] = mapped_column(String(32), default="")
    to_number: Mapped[str] = mapped_column(String(32), default="")

    status: Mapped[CallStatus] = mapped_column(
        StrEnumType(CallStatus, 16), default=CallStatus.INITIATED, index=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn(), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(600), nullable=True)

    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # True when at least one usage line had no verified rate: the number shown
    # is a floor, not the real cost. Never silently price an unknown rate.
    cost_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)


class CallTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "call_turns"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(16))  # agent | customer | system
    content: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    barge_in: Mapped[bool] = mapped_column(Boolean, default=False)
    spoken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One metered line item. The cost engine joins these against pricing_rates."""

    __tablename__ = "call_usage"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    component: Mapped[UsageComponent] = mapped_column(StrEnumType(UsageComponent, 16), index=True)
    provider: Mapped[str] = mapped_column(String(48))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str] = mapped_column(String(32))  # minute | character | token_in | token_out
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    priced: Mapped[bool] = mapped_column(Boolean, default=False)
