from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.campaign import CampaignLeadStatus, CampaignStatus


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    agent_id: uuid.UUID
    calling_hours_start: time = time(10, 0)
    calling_hours_end: time = time(19, 0)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    # Capped deliberately: uncontrolled parallel dialing is a cost and
    # compliance incident, not a throughput setting.
    max_concurrent_calls: int = Field(default=2, ge=1, le=50)
    delay_between_calls_seconds: int = Field(default=5, ge=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_delay_minutes: int = Field(default=180, ge=5, le=10080)
    budget_limit_usd: float | None = Field(default=None, ge=0)
    lead_ids: list[uuid.UUID] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    agent_id: uuid.UUID | None = None
    calling_hours_start: time | None = None
    calling_hours_end: time | None = None
    timezone: str | None = None
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=50)
    delay_between_calls_seconds: int | None = Field(default=None, ge=0, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_delay_minutes: int | None = Field(default=None, ge=5, le=10080)
    budget_limit_usd: float | None = Field(default=None, ge=0)


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    status: CampaignStatus
    calling_hours_start: time
    calling_hours_end: time
    timezone: str
    max_concurrent_calls: int
    delay_between_calls_seconds: int
    max_retries: int
    retry_delay_minutes: int
    budget_limit_usd: float | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class CampaignStats(BaseModel):
    total_leads: int
    pending: int
    completed: int
    failed: int
    calls_made: int
    active_calls: int
    cost_usd: float
    within_calling_hours: bool


class CampaignDetail(CampaignRead):
    stats: CampaignStats


class CampaignLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    status: CampaignLeadStatus
    attempts: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None


class AddLeadsRequest(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=10000)


class AddSheetRequest(BaseModel):
    """Put everyone on an uploaded sheet onto this campaign."""

    lead_list_id: uuid.UUID


class DispatchResult(BaseModel):
    started: int
    reason: str


class CampaignImportResult(BaseModel):
    """Outcome of uploading a CSV straight onto a campaign."""

    imported: int
    skipped: int
    #: How many of the file's people are now on this campaign's call list.
    #: Higher than `imported` when the file contained people you already had.
    attached: int
    errors: list[str]
