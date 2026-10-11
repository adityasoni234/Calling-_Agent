"""Bulk email: addresses, validation, campaigns and suppression.

Email is modelled apart from SMS and WhatsApp because its failure modes are
different in kind. A phone number is either reachable or it is not; an email
address can be syntactically perfect, have working MX records, and still be
a spam trap that ends your sending reputation. So validation is a recorded
verdict with a method and a confidence attached, not a boolean.

Three rules the schema enforces rather than trusting callers to remember:

* **A hard bounce suppresses the address permanently.** Sending again after
  one is how a domain gets blocked, and no campaign may override it.
* **Unsubscribe is forever and cross-campaign.** It belongs to the address,
  not to the list it arrived on.
* **Every send records the validation it passed.** When a provider asks why
  you mailed a dead address, the answer has to be in the row.
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


class EmailVerdict(enum.StrEnum):
    """What validation concluded. Deliberately not a boolean.

    `VALID` means every check we ran passed -- it is not a promise the
    address accepts mail, and nothing in this system claims otherwise.
    """

    #: Syntax, domain and MX all passed. Eligible to send.
    VALID = "valid"
    #: Reachable but carries a known risk: role account, disposable domain,
    #: catch-all. Sending is an org-level decision.
    RISKY = "risky"
    #: Syntax or domain failed. Never sent, in any configuration.
    INVALID = "invalid"
    #: On the suppression list. Never sent, in any configuration.
    SUPPRESSED = "suppressed"
    #: Checks could not complete -- DNS timed out. Retried, never assumed good.
    UNKNOWN = "unknown"


#: The two verdicts no setting may override. A campaign that could be
#: configured to mail a hard-bounced address is a campaign that will.
NEVER_SEND = frozenset({EmailVerdict.INVALID, EmailVerdict.SUPPRESSED})


class ValidationMethod(enum.StrEnum):
    SYNTAX = "syntax"
    DNS_MX = "dns_mx"
    SUPPRESSION = "suppression"
    #: An external verification service, when one is configured.
    PROVIDER = "provider"


class EmailSuppressionReason(enum.StrEnum):
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    UNSUBSCRIBED = "unsubscribed"
    MANUAL = "manual"
    INVALID = "invalid"
    BLOCKED_DOMAIN = "blocked_domain"


class EmailStatus(enum.StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    #: Permanent. Suppresses the address.
    BOUNCED = "bounced"
    #: Temporary. Does not suppress; the provider retries.
    DEFERRED = "deferred"
    #: Marked as spam by the recipient. Worse than a bounce.
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"
    FAILED = "failed"
    BLOCKED = "blocked"


TERMINAL_EMAIL_STATUSES = frozenset(
    {
        EmailStatus.BOUNCED,
        EmailStatus.COMPLAINED,
        EmailStatus.UNSUBSCRIBED,
        EmailStatus.FAILED,
        EmailStatus.BLOCKED,
    }
)


class EmailCampaignStatus(enum.StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    #: Validation finished; waiting for a human to approve the send.
    READY = "ready"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EmailAddress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A known address and the last verdict reached about it.

    Cached per organization so a 50,000-row import does not re-run DNS for
    an address checked last week, and so the verdict shown before a send is
    the same one used during it.
    """

    __tablename__ = "email_addresses"
    __table_args__ = (
        UniqueConstraint("organization_id", "address", name="uq_email_address_org"),
        Index("ix_email_address_verdict", "organization_id", "verdict"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    #: Lower-cased and trimmed. Deduplication depends on it.
    address: Mapped[str] = mapped_column(String(320), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)

    verdict: Mapped[EmailVerdict] = mapped_column(
        StrEnumType(EmailVerdict, 16), default=EmailVerdict.UNKNOWN
    )
    #: Which check produced the verdict, so a claim can be held to its method.
    method: Mapped[ValidationMethod] = mapped_column(
        StrEnumType(ValidationMethod, 16), default=ValidationMethod.SYNTAX
    )
    #: 0-100. Never 100: no check short of delivery proves an address works.
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Why it is risky, when it is: role account, disposable, catch-all.
    flags: Mapped[list] = mapped_column(JSONColumn(), default=list)
    bounce_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def sendable(self) -> bool:
        return self.verdict not in NEVER_SEND


class EmailSuppression(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An address that must never be mailed again.

    Separate from the address cache because a suppression outlives a
    re-validation: an address that hard-bounced still bounces when its MX
    records look fine again.
    """

    __tablename__ = "email_suppressions"
    __table_args__ = (
        UniqueConstraint("organization_id", "address", name="uq_email_suppression"),
        Index("ix_email_suppression_lookup", "organization_id", "address"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    address: Mapped[str] = mapped_column(String(320), index=True)
    reason: Mapped[EmailSuppressionReason] = mapped_column(StrEnumType(EmailSuppressionReason, 24))
    #: The provider's own wording. The useful part of a bounce.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL"), nullable=True
    )


class EmailCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bulk send, with its validation outcome attached.

    Validation runs before the campaign can leave DRAFT, so the counts a
    sender approves are the counts that get used.
    """

    __tablename__ = "email_campaigns"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[EmailCampaignStatus] = mapped_column(
        StrEnumType(EmailCampaignStatus, 16), default=EmailCampaignStatus.DRAFT
    )

    subject: Mapped[str] = mapped_column(String(500))
    preheader: Mapped[str | None] = mapped_column(String(300), nullable=True)
    html_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Required, not optional. A mail with no plain-text part scores worse in
    #: every spam filter that exists.
    text_body: Mapped[str] = mapped_column(Text, default="")

    from_name: Mapped[str] = mapped_column(String(120), default="")
    from_address: Mapped[str] = mapped_column(String(320), default="")
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)

    lead_list_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lead_lists.id", ondelete="SET NULL"), nullable=True
    )
    #: Whether addresses flagged risky may be included. Off by default; an
    #: org turns it on knowingly.
    include_risky: Mapped[bool] = mapped_column(Boolean, default=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emails_per_minute: Mapped[int] = mapped_column(Integer, default=120)

    # Validation outcome, frozen at approval time.
    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    risky_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Outcome.
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_count: Mapped[int] = mapped_column(Integer, default=0)
    bounced_count: Mapped[int] = mapped_column(Integer, default=0)
    complained_count: Mapped[int] = mapped_column(Integer, default=0)
    unsubscribed_count: Mapped[int] = mapped_column(Integer, default=0)

    estimated_charge_usd = mapped_column(MoneyAmount, nullable=True)
    actual_charge_usd = mapped_column(MoneyAmount, nullable=True)

    #: Who confirmed they have consent to mail this list, and when.
    consent_confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    consent_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def eligible_count(self) -> int:
        """How many will actually be mailed under the current setting."""
        return self.valid_count + (self.risky_count if self.include_risky else 0)


class EmailMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One email to one address."""

    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_email_idempotency"),
        Index("ix_email_message_org_time", "organization_id", "created_at"),
        Index("ix_email_message_provider", "provider_message_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    to_address: Mapped[str] = mapped_column(String(320), index=True)
    from_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    status: Mapped[EmailStatus] = mapped_column(
        StrEnumType(EmailStatus, 16), default=EmailStatus.DRAFT
    )

    #: The verdict this send was authorised under, copied at send time. Lets
    #: "why did you mail a dead address" be answered from the row itself.
    verdict_at_send: Mapped[str | None] = mapped_column(String(16), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(48), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider_cost_usd = mapped_column(MoneyAmount, nullable=True)
    customer_charge_usd = mapped_column(MoneyAmount, nullable=True)
    price_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_rules.id", ondelete="SET NULL"), nullable=True
    )
    cost_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)

    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Signed token in the unsubscribe link, so a click can be attributed
    #: without exposing the address in the URL.
    unsubscribe_token: Mapped[str | None] = mapped_column(String(64), index=True)

    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
