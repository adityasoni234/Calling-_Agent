"""A customer's own mailbox, connected by OAuth.

Each organization sends from an address they already own -- their Gmail or
Outlook account -- rather than from a shared platform sender. Three reasons
that is the right shape:

* **It is free.** Sending goes through the customer's existing mailbox and
  their own daily quota. The platform pays nothing per message.
* **Deliverability is theirs.** Mail arrives from a domain the recipient
  recognises, signed by a provider with a reputation, instead of from a
  shared IP whose reputation is the sum of every tenant's behaviour.
* **Nobody pastes a credential.** The customer approves access in Google's
  or Microsoft's own dialog; we never see a password and never ask for an
  API token.

Refresh tokens are the thing worth guarding. A Gmail refresh token can send
mail as that person indefinitely, so it is encrypted at rest with the same
vault the provider credentials use, never returned by any API, and deleted
rather than deactivated when the customer disconnects.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class MailboxProvider(enum.StrEnum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    #: App-password SMTP, for providers with no OAuth or a customer who
    #: prefers it. Still a credential, so it is not the default path.
    SMTP = "smtp"


class MailboxStatus(enum.StrEnum):
    CONNECTED = "connected"
    #: The refresh token was revoked or expired. Only the customer can fix
    #: it, by reconnecting; we cannot refresh our way out of it.
    EXPIRED = "expired"
    #: Connected, but the last send failed for another reason.
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class EmailAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One connected mailbox belonging to one organization."""

    __tablename__ = "email_accounts"
    __table_args__ = (UniqueConstraint("organization_id", "address", name="uq_email_account"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[MailboxProvider] = mapped_column(StrEnumType(MailboxProvider, 16))
    #: The address mail is sent from. Taken from the provider, not typed in,
    #: so it cannot disagree with what the mailbox will actually accept.
    address: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")

    #: Fernet ciphertext. Decrypted only when a send is being built.
    access_token: Mapped[str] = mapped_column(Text, default="")
    #: The long-lived half. Google issues it once, on first consent, so
    #: losing it means the customer has to reconnect.
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[list] = mapped_column(JSONColumn(), default=list)

    status: Mapped[MailboxStatus] = mapped_column(
        StrEnumType(MailboxStatus, 16), default=MailboxStatus.CONNECTED
    )
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)

    #: What the provider allows per day. Gmail is 500 for a personal account
    #: and 2,000 on Workspace; exceeding it suspends sending for 24 hours,
    #: so it is tracked rather than discovered.
    daily_limit: Mapped[int] = mapped_column(Integer, default=500)
    sent_today: Mapped[int] = mapped_column(Integer, default=0)
    quota_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.sent_today)

    @property
    def is_usable(self) -> bool:
        return self.status is MailboxStatus.CONNECTED and self.remaining_today > 0
