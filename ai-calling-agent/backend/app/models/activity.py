"""Domain activity: what people actually did, not just what admins did.

`platform_events` records administrator actions against customers. It cannot
answer "what is this user doing in the product", because customers' own work
was never recorded anywhere.

Append-only. A correction is a new row, never an edit -- an audit trail that can
be rewritten is not one.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class ActorType(enum.StrEnum):
    """Who did it. Distinguishing these is the point of the table."""

    USER = "user"
    #: An external system authenticated with an API key.
    API_KEY = "api_key"
    #: A scheduled job or dispatcher tick. No human involved.
    SYSTEM = "system"
    #: Platform staff acting on a customer's account.
    PLATFORM_ADMIN = "platform_admin"


class EntityType(enum.StrEnum):
    AGENT = "agent"
    CAMPAIGN = "campaign"
    CALL = "call"
    LEAD = "lead"
    LEAD_LIST = "lead_list"
    KNOWLEDGE_BASE = "knowledge_base"
    DOCUMENT = "document"
    API_KEY = "api_key"
    WEBHOOK = "webhook"
    ORGANIZATION = "organization"
    USER = "user"
    CREDIT = "credit"
    PRICING = "pricing"


class ActivityEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One meaningful thing that happened, attributable to someone.

    Deliberately not a page-view log: only writes and lifecycle transitions, so
    the timeline stays readable and the table stays affordable.
    """

    __tablename__ = "activity_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    #: Null only when genuinely unknown -- a dispatcher tick, or a record that
    #: predates attribution. Never filled with a guess.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Snapshot, so a deleted or renamed user does not erase the history.
    actor_label: Mapped[str | None] = mapped_column(String(320), nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(
        StrEnumType(ActorType, 16), default=ActorType.USER, index=True
    )

    #: Dotted and past tense: "campaign.started", "agent.updated".
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[EntityType] = mapped_column(StrEnumType(EntityType, 24), index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    #: Human-readable name at the time, so a deep link that 404s still means something.
    entity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: Only the fields that changed, never the whole row, and never a secret.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn(), nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn(), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Ties an event to the request that caused it, for tracing a failure.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
