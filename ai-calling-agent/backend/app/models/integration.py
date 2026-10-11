"""Integration surface: how an external CRM authenticates and gets told things.

Two halves, because an integration needs both directions. An API key lets a CRM
call in without a browser login. A webhook endpoint lets us call out when
something happens, so the CRM does not have to poll.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class WebhookEvent(enum.StrEnum):
    """What an integration can subscribe to.

    Deliberately small: these are the moments a CRM actually needs to react to.
    """

    CALL_STARTED = "call.started"
    CALL_COMPLETED = "call.completed"
    LEAD_QUALIFIED = "lead.qualified"
    LEAD_STATUS_CHANGED = "lead.status_changed"


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-lived credential for machine callers.

    Only the hash is stored. The plaintext is shown once, at creation, and can
    never be recovered -- the same reason passwords are hashed.
    """

    __tablename__ = "api_keys"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    #: First characters of the key, so a person can tell two keys apart in a list.
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hashed_key: Mapped[str] = mapped_column(String(128))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Where to POST when something happens."""

    __tablename__ = "webhook_endpoints"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(600))
    #: Shared secret. Every delivery is signed with it so the receiver can prove
    #: the request came from us and not from anyone who guessed the URL.
    secret: Mapped[str] = mapped_column(String(128))
    events: Mapped[list[str]] = mapped_column(JSONColumn(), default=list)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Consecutive failures. A dead endpoint disables itself rather than
    #: retrying forever against a URL nobody is listening on.
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookDeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One attempt to tell an endpoint about one event.

    Kept so an integrator can see what we sent and what came back, which is the
    first question asked whenever a webhook "did not arrive".
    """

    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[WebhookEvent] = mapped_column(StrEnumType(WebhookEvent, 40), index=True)
    payload: Mapped[dict] = mapped_column(JSONColumn(), default=dict)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        StrEnumType(WebhookDeliveryStatus, 16), default=WebhookDeliveryStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
