from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.call import CallDirection, CallStatus, UsageComponent


class CallCreate(BaseModel):
    agent_id: uuid.UUID
    lead_id: uuid.UUID | None = None
    to_number: str | None = Field(default=None, max_length=32)
    from_number: str | None = Field(default=None, max_length=32)


class CallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    lead_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    direction: CallDirection
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
    quantity: float
    cost_usd: float | None
    priced: bool


class CallDetail(CallRead):
    turns: list[CallTurnRead]
    usage: list[CallUsageRead]
