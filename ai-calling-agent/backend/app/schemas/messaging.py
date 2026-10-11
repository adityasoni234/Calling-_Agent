"""Messaging request and response shapes.

Money leaves as a string, not a float. JSON numbers are IEEE doubles, so
serialising a Decimal charge as a number hands the browser back the drift
this platform spent a migration removing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.messaging import Channel, ConsentMethod, SuppressionReason


class _Money(BaseModel):
    """Serialises every Decimal field as a string."""

    @field_serializer("*", when_used="json")
    def _decimals_as_strings(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class MessageSend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_number: str = Field(min_length=3, max_length=32)
    channel: Channel = Channel.SMS
    body: str | None = Field(default=None, max_length=4096)
    template_id: uuid.UUID | None = None
    template_variables: dict[str, str] = Field(default_factory=dict)
    from_number: str | None = None
    lead_id: uuid.UUID | None = None
    #: Supplied by the caller so a retry cannot send twice.
    idempotency_key: str | None = Field(default=None, max_length=120)
    require_consent: bool = False


class MessageRead(_Money):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    channel: str
    direction: str
    status: str
    from_number: str
    to_number: str
    body: str | None
    segments: int
    region: str | None
    provider: str | None
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    customer_charge_usd: Decimal | None
    provider_cost_usd: Decimal | None
    cost_incomplete: bool
    suppression_reason: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    contact_number: str
    contact_name: str | None
    lead_id: uuid.UUID | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    unread_count: int
    is_archived: bool
    #: Whether a free-form WhatsApp reply is allowed right now. Computed, so
    #: the UI does not re-derive the 24-hour rule and get it slightly wrong.
    session_open: bool = False
    created_at: datetime


class EstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel = Channel.SMS
    recipients: list[str] = Field(min_length=1, max_length=50_000)
    body: str | None = Field(default=None, max_length=4096)
    template_id: uuid.UUID | None = None


class TemplateWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    channel: Channel = Channel.WHATSAPP
    language: str = Field(default="en", max_length=16)
    category: str | None = Field(default=None, max_length=48)
    body: str = Field(min_length=1, max_length=4096)
    variables: list[str] = Field(default_factory=list)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    name: str
    language: str
    category: str | None
    body: str
    variables: list
    status: str
    rejection_reason: str | None
    provider_template_id: str | None
    placeholder_count: int = 0
    created_at: datetime


class SuppressionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_number: str = Field(min_length=3, max_length=32)
    channel: Channel | None = None
    reason: SuppressionReason = SuppressionReason.MANUAL
    note: str | None = Field(default=None, max_length=1000)


class SuppressionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_number: str
    channel: str | None
    reason: str
    note: str | None
    created_at: datetime


class ConsentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_number: str = Field(min_length=3, max_length=32)
    channel: Channel | None = None
    method: ConsentMethod = ConsentMethod.WEB_FORM
    evidence: dict = Field(default_factory=dict)


class ConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_number: str
    channel: str | None
    method: str
    granted_at: datetime
    revoked_at: datetime | None
    evidence: dict


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    channel: Channel = Channel.SMS
    body: str | None = Field(default=None, max_length=4096)
    template_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    from_number: str | None = None
    #: Carriers rate-limit, and a sender that bursts gets flagged.
    messages_per_minute: int = Field(default=60, ge=1, le=600)
    scheduled_at: datetime | None = None


class CampaignRead(_Money):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    channel: str
    status: str
    body: str | None
    template_id: uuid.UUID | None
    lead_list_id: uuid.UUID | None
    from_number: str | None
    messages_per_minute: int
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    total_recipients: int
    sent_count: int
    delivered_count: int
    failed_count: int
    suppressed_count: int
    estimated_charge_usd: Decimal | None
    actual_charge_usd: Decimal | None
    created_at: datetime
    #: Server-computed so the UI never re-derives it and disagrees.
    percent_complete: int = 0
    remaining: int = 0
