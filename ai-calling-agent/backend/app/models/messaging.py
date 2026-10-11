"""SMS and WhatsApp: messages, conversations, templates, consent.

Modelled separately from calls rather than as a `Call` with a flag. A message
has no duration, can be inbound without ringing anything, arrives in a thread,
and on WhatsApp may legally require a pre-approved template. Sharing a table
would have meant a column that is null for one kind on nearly every row.

Four rules are enforced by the schema rather than by remembering:

* **Opt-out is a hard gate.** A suppression row blocks a send; it is not a
  flag a caller may choose to honour.
* **Consent is a record, not a boolean.** When and how someone opted in is
  what makes a send defensible later.
* **Idempotency is per-tenant.** A retried bulk campaign must not double-send,
  and two tenants must be free to use the same client key.
* **Money is NUMERIC.** Same reason as everywhere else.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import MoneyAmount
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class Channel(enum.StrEnum):
    SMS = "sms"
    WHATSAPP = "whatsapp"


class MessageDirection(enum.StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class MessageStatus(enum.StrEnum):
    """The lifecycle a carrier actually reports.

    `QUEUED` and `SENT` are ours and the carrier's "accepted"; `DELIVERED`,
    `UNDELIVERED` and `FAILED` come from the delivery receipt, which can
    arrive minutes later. `UNDELIVERED` is distinct from `FAILED`: the carrier
    took the message and could not deliver it, which is billable, whereas a
    rejected send is not.
    """

    DRAFT = "draft"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    UNDELIVERED = "undelivered"
    FAILED = "failed"
    #: Blocked before dispatch by opt-out, DND or a missing consent record.
    SUPPRESSED = "suppressed"


#: Nothing further will happen to a message in one of these.
TERMINAL_MESSAGE_STATUSES = frozenset(
    {
        MessageStatus.DELIVERED,
        MessageStatus.READ,
        MessageStatus.UNDELIVERED,
        MessageStatus.FAILED,
        MessageStatus.SUPPRESSED,
    }
)
#: The carrier accepted and will bill us, whatever happens next.
BILLABLE_MESSAGE_STATUSES = frozenset(
    {
        MessageStatus.SENT,
        MessageStatus.DELIVERED,
        MessageStatus.READ,
        MessageStatus.UNDELIVERED,
    }
)


class TemplateStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    DISABLED = "disabled"


class SuppressionReason(enum.StrEnum):
    OPT_OUT = "opt_out"
    #: National do-not-call registry.
    DND = "dnd"
    COMPLAINT = "complaint"
    MANUAL = "manual"
    INVALID_NUMBER = "invalid_number"


class ConsentMethod(enum.StrEnum):
    WEB_FORM = "web_form"
    IMPORT = "import"
    VERBAL_ON_CALL = "verbal_on_call"
    INBOUND_MESSAGE = "inbound_message"
    API = "api"


class MessageCampaignStatus(enum.StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One thread with one contact on one channel.

    Keyed on (org, channel, contact) so an inbound reply lands in the existing
    thread instead of starting a new one. WhatsApp and SMS to the same number
    are different threads: they have different senders, rules and costs.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "channel", "contact_number", name="uq_conversation_scope"
        ),
        Index("ix_conversation_recent", "organization_id", "last_message_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[Channel] = mapped_column(StrEnumType(Channel, 16))
    #: E.164. Normalised on write so one contact is one thread.
    contact_number: Mapped[str] = mapped_column(String(32), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def session_open(self) -> bool:
        """WhatsApp allows free-form replies only within 24h of an inbound.

        Outside it the send must use an approved template. Computing this from
        the stored timestamp keeps one definition instead of each call site
        inventing its own window.
        """
        from datetime import UTC, timedelta

        from app.core.times import as_utc

        last = as_utc(self.last_inbound_at)
        if last is None:
            return False
        return (datetime.now(UTC) - last) < timedelta(hours=24)


class MessageTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pre-approved WhatsApp template, or a reusable SMS body.

    Approval belongs to the provider, so `status` mirrors what they told us
    and is never set optimistically on our side. Sending on a template that is
    not APPROVED is what gets a WhatsApp sender banned.
    """

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", "channel", name="uq_template_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[Channel] = mapped_column(StrEnumType(Channel, 16))
    name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(16), default="en")
    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: "Hi {{1}}, your call is booked for {{2}}."
    body: Mapped[str] = mapped_column(Text)
    #: Ordered names for the positional placeholders, for the UI to label.
    variables: Mapped[list] = mapped_column(JSONColumn(), default=list)

    status: Mapped[TemplateStatus] = mapped_column(
        StrEnumType(TemplateStatus, 16), default=TemplateStatus.DRAFT
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The provider's own id, needed to send.
    provider_template_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def placeholder_count(self) -> int:
        import re

        return len(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", self.body)))


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One SMS or WhatsApp message.

    Carries its own money columns rather than deriving them later: the price
    in force when it was sent is a fact about the message, and recomputing it
    from today's price book would rewrite history.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_message_idempotency"),
        Index("ix_message_org_time", "organization_id", "created_at"),
        Index("ix_message_status", "status", "created_at"),
        Index("ix_message_provider_sid", "provider_message_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Who pressed send. Null for inbound and for scheduled campaign sends.
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )

    channel: Mapped[Channel] = mapped_column(StrEnumType(Channel, 16), index=True)
    direction: Mapped[MessageDirection] = mapped_column(StrEnumType(MessageDirection, 16))
    status: Mapped[MessageStatus] = mapped_column(
        StrEnumType(MessageStatus, 16), default=MessageStatus.DRAFT
    )

    from_number: Mapped[str] = mapped_column(String(32))
    to_number: Mapped[str] = mapped_column(String(32), index=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_urls: Mapped[list] = mapped_column(JSONColumn(), default=list)

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True
    )
    template_variables: Mapped[dict] = mapped_column(JSONColumn(), default=dict)

    #: A long SMS is split and billed per part, so this is what we pay for.
    segments: Mapped[int] = mapped_column(Integer, default=1)
    #: ISO country of the destination; drives destination-specific pricing.
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(48), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: What the provider charged, in their currency, and converted.
    provider_cost = mapped_column(MoneyAmount, nullable=True)
    provider_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    provider_cost_usd = mapped_column(MoneyAmount, nullable=True)
    #: What we charged, and the rule that decided it.
    customer_charge_usd = mapped_column(MoneyAmount, nullable=True)
    price_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_rules.id", ondelete="SET NULL"), nullable=True
    )
    credits_charged = mapped_column(MoneyAmount, nullable=True)
    #: True when a cost component had no verified rate; blocks any margin claim.
    cost_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)

    #: Caller-supplied, unique per tenant. A retried bulk send must not
    #: double-charge or double-deliver.
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)

    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bulk send. Separate from the voice `Campaign` for the same reasons."""

    __tablename__ = "message_campaigns"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[Channel] = mapped_column(StrEnumType(Channel, 16))
    status: Mapped[MessageCampaignStatus] = mapped_column(
        StrEnumType(MessageCampaignStatus, 16), default=MessageCampaignStatus.DRAFT
    )

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lead_list_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lead_lists.id", ondelete="SET NULL"), nullable=True
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Protects a tenant's sender reputation and respects carrier limits.
    messages_per_minute: Mapped[int] = mapped_column(Integer, default=60)

    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)

    #: Quoted before launch so the sender sees the bill before committing.
    estimated_cost_usd = mapped_column(MoneyAmount, nullable=True)
    estimated_charge_usd = mapped_column(MoneyAmount, nullable=True)
    actual_charge_usd = mapped_column(MoneyAmount, nullable=True)


class Suppression(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A number we must not message. Checked before every send.

    Scoped per channel: someone may stop WhatsApp and still want SMS. A NULL
    channel suppresses both, which is what a complaint should do.
    """

    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "contact_number", "channel", name="uq_suppression_scope"
        ),
        Index("ix_suppression_lookup", "organization_id", "contact_number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    contact_number: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[Channel | None] = mapped_column(StrEnumType(Channel, 16), nullable=True)
    reason: Mapped[SuppressionReason] = mapped_column(StrEnumType(SuppressionReason, 24))
    #: The exact inbound that opted them out, so the decision is evidenced.
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConsentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Evidence that someone agreed to be contacted.

    A boolean on the lead would say "yes" without saying when, how, or on what
    wording -- which is precisely what is asked for when a complaint arrives.
    """

    __tablename__ = "consent_records"
    __table_args__ = (Index("ix_consent_lookup", "organization_id", "contact_number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    contact_number: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[Channel | None] = mapped_column(StrEnumType(Channel, 16), nullable=True)
    method: Mapped[ConsentMethod] = mapped_column(StrEnumType(ConsentMethod, 24))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The wording shown, the IP, the file imported from.
    evidence: Mapped[dict] = mapped_column(JSONColumn(), default=dict)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
