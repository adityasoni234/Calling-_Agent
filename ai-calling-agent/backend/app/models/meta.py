"""Meta (Facebook/Instagram) lead-ad connections.

A customer connects their own Business, Ad Account, Page and Lead Form
through Meta's OAuth, and leads arrive by webhook as people submit them.

Tokens are the whole security story here. A Meta user token can read a
business's ad data and post as their Page, so it is encrypted at rest with
the same vault the provider credentials use, never returned by any API, and
never sent to a browser. Only the masked tail and the expiry are readable.

Meta's own model is mirrored rather than flattened: a Business owns Ad
Accounts and Pages, a Page owns Lead Forms, and a lead names the form, the
ad and the campaign it came from. Collapsing that would lose the
attribution, which is the main reason to connect at all.
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

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class MetaConnectionStatus(enum.StrEnum):
    #: OAuth completed and the token works.
    CONNECTED = "connected"
    #: Token expired or was revoked in Meta. Needs the user to reconnect;
    #: we cannot fix it from this side.
    EXPIRED = "expired"
    #: Connected but the last call failed for another reason.
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class MetaAssetKind(enum.StrEnum):
    BUSINESS = "business"
    AD_ACCOUNT = "ad_account"
    PAGE = "page"
    LEAD_FORM = "lead_form"
    WHATSAPP = "whatsapp"


class MetaConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One customer's authorisation to read their Meta lead data."""

    __tablename__ = "meta_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "meta_user_id", name="uq_meta_connection"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Meta's id for the person who authorised, not for the business.
    meta_user_id: Mapped[str] = mapped_column(String(64), index=True)
    meta_user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: Fernet ciphertext. The only plaintext read is at the moment a Graph
    #: call is built.
    access_token: Mapped[str] = mapped_column(Text)
    #: Last four characters, safe to display and to log.
    token_hint: Mapped[str] = mapped_column(String(32), default="")
    #: Meta long-lived tokens last about 60 days. Checked before use so an
    #: expiry surfaces as "reconnect" rather than as failing lead delivery.
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: What the user actually granted. Meta can issue fewer scopes than were
    #: requested, and a missing one fails later in a way that looks unrelated.
    scopes: Mapped[list] = mapped_column(JSONColumn(), default=list)

    status: Mapped[MetaConnectionStatus] = mapped_column(
        StrEnumType(MetaConnectionStatus, 16), default=MetaConnectionStatus.CONNECTED
    )
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_lead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leads_received: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def is_usable(self) -> bool:
        from app.core.times import as_utc

        if self.status is not MetaConnectionStatus.CONNECTED:
            return False
        expiry = as_utc(self.token_expires_at)
        if expiry is None:
            return True
        from datetime import UTC
        from datetime import datetime as _dt

        return expiry > _dt.now(UTC)


class MetaAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Business, Ad Account, Page or Lead Form the customer selected.

    Stored flat with a parent pointer rather than as four tables: the shape
    is a tree of the same thing, and four tables would mean four joins to
    answer "which form did this lead come from".
    """

    __tablename__ = "meta_assets"
    __table_args__ = (
        UniqueConstraint("connection_id", "meta_id", name="uq_meta_asset"),
        Index("ix_meta_asset_kind", "organization_id", "kind"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meta_connections.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[MetaAssetKind] = mapped_column(StrEnumType(MetaAssetKind, 16))
    meta_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(300))
    #: Meta id of the owning asset, so the tree can be walked without joins.
    parent_meta_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Whether leads from this form are ingested. Selecting a Page should not
    #: silently subscribe every form on it.
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Whether the webhook subscription was accepted by Meta for this asset.
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Page access token, where Meta issues a separate one. Encrypted.
    page_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONColumn(), default=dict)


class MetaLeadEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One lead-submission webhook, recorded before it is processed.

    Written first and processed second, so a crash mid-processing loses
    nothing and a duplicate delivery -- which Meta does send -- is detected
    by the unique leadgen id rather than creating a second lead.
    """

    __tablename__ = "meta_lead_events"
    __table_args__ = (
        UniqueConstraint("leadgen_id", name="uq_meta_leadgen"),
        Index("ix_meta_lead_event_org", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meta_connections.id", ondelete="SET NULL"), nullable=True
    )
    #: Meta's id for this submission. The deduplication key.
    leadgen_id: Mapped[str] = mapped_column(String(64), index=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ad_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: The created Lead, once the field data has been fetched and mapped.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The webhook body and, once fetched, the form field values.
    raw: Mapped[dict] = mapped_column(JSONColumn(), default=dict)
