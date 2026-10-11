"""Email request and response shapes. Money leaves as a string, never a float."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class _Money(BaseModel):
    @field_serializer("*", when_used="json")
    def _decimals_as_strings(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addresses: list[str] = Field(min_length=1, max_length=50_000)
    #: Skipping DNS is faster and honest about it: the verdict comes back
    #: unknown rather than pretending the domain was checked.
    check_dns: bool = True


class EmailSend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_address: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    text_body: str = Field(min_length=1, max_length=100_000)
    html_body: str | None = Field(default=None, max_length=500_000)
    from_address: str | None = None
    from_name: str | None = Field(default=None, max_length=120)
    reply_to: str | None = None
    lead_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=160)
    allow_risky: bool = False


class EmailMessageRead(_Money):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID | None
    to_address: str
    from_address: str
    subject: str
    status: str
    #: The validation verdict this send was authorised under.
    verdict_at_send: str | None
    provider: str | None
    error_code: str | None
    error_message: str | None
    customer_charge_usd: Decimal | None
    cost_incomplete: bool
    sent_at: datetime | None
    delivered_at: datetime | None
    opened_at: datetime | None
    created_at: datetime


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=500)
    text_body: str = Field(min_length=1, max_length=100_000)
    html_body: str | None = Field(default=None, max_length=500_000)
    from_address: str = Field(min_length=3, max_length=320)
    from_name: str = Field(default="", max_length=120)
    reply_to: str | None = None
    lead_list_id: uuid.UUID | None = None
    include_risky: bool = False
    scheduled_at: datetime | None = None
    emails_per_minute: int = Field(default=120, ge=1, le=5000)


class EmailCampaignRead(_Money):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    subject: str
    from_address: str
    from_name: str
    include_risky: bool
    total_recipients: int
    valid_count: int
    risky_count: int
    invalid_count: int
    suppressed_count: int
    unknown_count: int
    sent_count: int
    delivered_count: int
    opened_count: int
    clicked_count: int
    bounced_count: int
    complained_count: int
    unsubscribed_count: int
    estimated_charge_usd: Decimal | None
    actual_charge_usd: Decimal | None
    validated_at: datetime | None
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    consent_confirmed_at: datetime | None
    created_at: datetime
    #: Computed server-side so the UI never re-derives the include_risky rule.
    eligible_count: int = 0


class SuppressionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    reason: str
    detail: str | None
    created_at: datetime


class SuppressionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=3, max_length=320)
    reason: str = "manual"
    detail: str | None = Field(default=None, max_length=500)
