"""Platform staff looking at a customer's account through the customer's own UI.

Support cannot debug what it cannot see. A screenshot from a frustrated
customer does not show which agent is misconfigured, and "works on my
account" is not a diagnosis. So staff need a way in.

The danger is not the looking -- it is what a session that can look can also
do. An impersonated session holds a real customer's identity, so without
limits it could spend their credits, dial their leads or email their list,
and the ledger would say the customer did it. Four things stop that:

* A session is a database row, not just a signed claim. A token whose row is
  ended or expired stops working immediately; a stolen token cannot outlive
  the session it came from.
* Thirty minutes, and no refresh token. A session that can be silently
  renewed is a permanent back door with a short name.
* Money and outbound messaging are refused outright, whatever the mode. No
  reason good enough to justify spending someone else's money while wearing
  their face has ever been written in a reason box.
* It is recorded twice -- once for us in `platform_events`, and once in the
  customer's own activity timeline, because a customer who cannot see that
  staff entered their account has not been told.

The handoff is a single-use code rather than a token in a URL. The admin and
customer apps are separate origins, so the token cannot simply be written to
the other's storage, and a token in a query string ends up in history, logs
and referrers.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType

#: How long a session lives. Long enough to reproduce a problem, short enough
#: that an unattended tab is not an open door.
SESSION_MINUTES = 30

#: How long the handoff code is worth anything. It only has to survive a
#: redirect between two tabs.
HANDOFF_SECONDS = 60

#: A reason short enough to be meaningless is worse than no box at all -- it
#: trains people to type "test" and makes the audit trail look complete.
MIN_REASON_LENGTH = 12


class ImpersonationMode(enum.StrEnum):
    """What the session is allowed to change."""

    #: Look, do not touch. The default, and what almost every support
    #: question actually needs.
    READ_ONLY = "read_only"
    #: Writes allowed, so staff can fix a misconfiguration the customer
    #: cannot describe well enough to fix themselves. Money and outbound
    #: messaging stay refused.
    READ_WRITE = "read_write"


class ImpersonationEndReason(enum.StrEnum):
    #: The impersonator clicked out.
    EXITED = "exited"
    #: A platform admin ended someone's session from the console.
    REVOKED = "revoked"
    #: Ran out the clock. Written lazily, the first time anything notices.
    EXPIRED = "expired"
    #: The target account was suspended or deactivated underneath it.
    TARGET_DISABLED = "target_disabled"


class ImpersonationSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One staff visit to one customer account."""

    __tablename__ = "impersonation_sessions"

    #: SET NULL rather than CASCADE: if a staff account is deleted the record
    #: of what it did must survive, which is why the email is snapshotted.
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    admin_email: Mapped[str] = mapped_column(String(320))

    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_email: Mapped[str] = mapped_column(String(320))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    #: Snapshot: the name at the time, so a later rename does not rewrite history.
    organization_name: Mapped[str] = mapped_column(String(200))

    mode: Mapped[ImpersonationMode] = mapped_column(
        StrEnumType(ImpersonationMode, 16), default=ImpersonationMode.READ_ONLY
    )
    reason: Mapped[str] = mapped_column(Text)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[ImpersonationEndReason | None] = mapped_column(
        StrEnumType(ImpersonationEndReason, 16), nullable=True
    )

    #: Only the digest. A code that can be read back out of the table is a
    #: credential sitting in a table.
    handoff_digest: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    handoff_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Set the first time the code is exchanged, which is also what makes it
    #: single-use. A second attempt is a replay and is refused.
    handoff_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Where the session was opened from, for the "was this really us" question.
    started_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    #: Counted rather than inferred, so the audit row can say whether the
    #: visit was passive. Counted on admission, not on success: a handler that
    #: failed afterwards still had its chance to change something.
    writes_performed: Mapped[int] = mapped_column(default=0)

    #: Kept so an ended session still reports why it cannot be reused, rather
    #: than looking merely absent.
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
