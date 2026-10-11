from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.call import CallDirection, CallMode, CallSource, CallStatus, UsageComponent


class CallCreate(BaseModel):
    agent_id: uuid.UUID
    lead_id: uuid.UUID | None = None
    to_number: str | None = Field(default=None, max_length=32)
    from_number: str | None = Field(default=None, max_length=32)


class BridgeCallRequest(BaseModel):
    """Ring me, then connect me to this person."""

    model_config = ConfigDict(extra="forbid")

    #: The phone the operator will answer on.
    operator_number: str = Field(min_length=6, max_length=32)
    lead_id: uuid.UUID | None = None
    to_number: str | None = Field(default=None, max_length=32)
    record: bool = True


class CallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    direction: CallDirection
    mode: CallMode
    operator_number: str | None
    #: Who started it, and how. Null initiator means a campaign tick or an
    #: inbound route placed the call, not a person.
    initiated_by_user_id: uuid.UUID | None
    source: CallSource
    source_detail: str | None
    agent_version: int | None
    provider: str
    provider_call_id: str | None
    from_number: str
    to_number: str
    status: CallStatus
    end_reason: str | None
    error: str | None
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    summary: str | None
    extracted_data: dict[str, Any] | None
    recording_url: str | None
    cost_usd: float
    cost_incomplete: bool
    created_at: datetime


class CallTurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    turn_index: int
    role: str
    content: str
    state: str | None
    latency_ms: int | None
    barge_in: bool
    spoken_at: datetime | None


class CallUsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component: UsageComponent
    provider: str
    model: str | None
    unit: str
    region: str | None
    quantity: float
    cost_usd: float | None
    priced: bool


class CallDetail(CallRead):
    turns: list[CallTurnRead]
    usage: list[CallUsageRead]
