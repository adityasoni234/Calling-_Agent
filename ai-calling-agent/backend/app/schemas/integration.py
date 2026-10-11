"""Schemas for the CRM integration surface."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.integration import WebhookEvent


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Carries the plaintext key. Returned once, on creation, and never again."""

    key: str


class WebhookEndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=600)
    events: list[WebhookEvent] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _must_be_https(cls, value: str) -> str:
        url = value.strip()
        # Event payloads carry lead names and phone numbers; sending those over
        # plain http would put them on the wire in clear text.
        if not url.startswith("https://") and not url.startswith("http://localhost"):
            raise ValueError("Webhook URL must be https (http allowed only for localhost)")
        return url


class WebhookEndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[WebhookEvent] | None = None
    description: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class WebhookEndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    events: list[str]
    description: str | None
    is_active: bool
    failure_count: int
    last_delivery_at: datetime | None
    last_error: str | None
    created_at: datetime


class WebhookEndpointCreated(WebhookEndpointRead):
    """Carries the signing secret, shown once so the receiver can verify us."""

    secret: str


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    event: str
    status: str
    attempts: int
    response_code: int | None
    error: str | None
    created_at: datetime
