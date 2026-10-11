"""Sending SMS and WhatsApp.

Every send passes the same gauntlet, in this order, and the order matters:

1. **Normalise** the destination to E.164. A number stored three ways is three
   contacts, three threads, and an opt-out that silently fails to match.
2. **Suppress** -- opt-out, DND, complaint. Checked before anything is
   reserved or sent, and recorded as a message in `SUPPRESSED` state rather
   than dropped, so "why did this person not get it?" is answerable.
3. **Template rules** -- WhatsApp outside a 24-hour session needs an approved
   template. Sending free-form anyway is what gets a sender banned.
4. **Quote** through the pricing engine. Never a price computed at the call
   site.
5. **Reserve** credits, then send, then settle against what the provider
   actually charged, releasing the remainder.

Idempotency wraps the whole thing: a retried request with the same key
returns the original message instead of sending a second one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import phonenumbers
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.money import ZERO, quantize_cost, to_decimal
from app.models.messaging import (
    Channel,
    ConsentRecord,
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
    MessageTemplate,
    Suppression,
    TemplateStatus,
)
from app.models.price_book import Billable
from app.services.pricing_engine import PricingEngine, Quote

log = get_logger(__name__)

#: GSM-7 fits 160 characters in one part, 153 per part once concatenated.
#: Any character outside it forces UCS-2 at 70 and 67. Getting this wrong
#: understates the bill on exactly the messages customers send most: the ones
#: with an emoji or a rupee sign in them.
GSM7_SINGLE, GSM7_MULTI = 160, 153
UCS2_SINGLE, UCS2_MULTI = 70, 67

_GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
) | set("^{}\\[~]|€")


class SendBlocked(AppError):
    """A send was refused before dispatch. Carries why, for the caller to show."""

    def __init__(self, message: str, *, code: str = "send_blocked") -> None:
        super().__init__(message, code=code)


def normalise_number(raw: str, *, default_region: str = "IN") -> tuple[str, str | None]:
    """E.164 plus ISO country, or raise.

    The country is returned because pricing is destination-specific: an SMS to
    the UK and one to India are different products at different costs.
    """
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as exc:
        raise SendBlocked(f"{raw!r} is not a usable phone number", code="bad_number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise SendBlocked(f"{raw!r} is not a valid phone number", code="bad_number")
    return (
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        phonenumbers.region_code_for_number(parsed),
    )


def count_segments(body: str) -> int:
    """How many parts a carrier will bill this as.

    Not `len(body) / 160`. One emoji in an otherwise plain message drops the
    whole thing to 70 characters per part and can triple the cost.
    """
    if not body:
        return 1
    length = len(body)
    unicode_needed = any(ch not in _GSM7 for ch in body)
    single, multi = (UCS2_SINGLE, UCS2_MULTI) if unicode_needed else (GSM7_SINGLE, GSM7_MULTI)
    if length <= single:
        return 1
    return -(-length // multi)  # ceiling division


@dataclass
class SendEstimate:
    """What a send will cost, before anyone commits to it."""

    recipients: int
    suppressed: int
    segments: int
    quote: Quote

    def as_dict(self) -> dict:
        return {
            "recipients": self.recipients,
            "suppressed": self.suppressed,
            "billable_recipients": self.recipients - self.suppressed,
            "segments_per_message": self.segments,
            "total_segments": self.segments * (self.recipients - self.suppressed),
            **self.quote.as_dict(),
        }


class MessagingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingEngine(db)

    # --- gates ---------------------------------------------------------

    async def is_suppressed(
        self, organization_id: uuid.UUID, number: str, channel: Channel
    ) -> Suppression | None:
        """A channel-specific block, or a global one. Either stops the send."""
        rows = await self.db.execute(
            select(Suppression).where(
                Suppression.organization_id == organization_id,
                Suppression.contact_number == number,
            )
        )
        for row in rows.scalars():
            if row.channel is None or row.channel == channel:
                return row
        return None

    async def has_consent(self, organization_id: uuid.UUID, number: str, channel: Channel) -> bool:
        rows = await self.db.execute(
            select(ConsentRecord).where(
                ConsentRecord.organization_id == organization_id,
                ConsentRecord.contact_number == number,
                ConsentRecord.revoked_at.is_(None),
            )
        )
        return any(r.channel in (None, channel) for r in rows.scalars())

    async def opt_out(
        self,
        organization_id: uuid.UUID,
        number: str,
        *,
        reason,
        channel: Channel | None = None,
        source_message_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> Suppression:
        """Record a suppression, idempotently.

        Opting out twice must not raise: the second STOP from someone already
        unsubscribed is the most normal thing in the world.
        """
        number, _ = normalise_number(number)
        existing = await self.db.execute(
            select(Suppression).where(
                Suppression.organization_id == organization_id,
                Suppression.contact_number == number,
                Suppression.channel == channel,
            )
        )
        found = existing.scalars().first()
        if found is not None:
            return found

        suppression = Suppression(
            organization_id=organization_id,
            contact_number=number,
            channel=channel,
            reason=reason,
            source_message_id=source_message_id,
            note=note,
        )
        self.db.add(suppression)
        # Any revoked consent must go with it, or the two records disagree.
        consents = await self.db.execute(
            select(ConsentRecord).where(
                ConsentRecord.organization_id == organization_id,
                ConsentRecord.contact_number == number,
                ConsentRecord.revoked_at.is_(None),
            )
        )
        for consent in consents.scalars():
            if consent.channel in (None, channel) or channel is None:
                consent.revoked_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(suppression)
        return suppression

    async def _check_template(
        self,
        organization_id: uuid.UUID,
        channel: Channel,
        conversation: Conversation | None,
        template: MessageTemplate | None,
    ) -> None:
        """WhatsApp's session rule, enforced rather than documented."""
        if channel is not Channel.WHATSAPP:
            return
        if conversation is not None and conversation.session_open:
            return
        if template is None:
            raise SendBlocked(
                "WhatsApp needs an approved template outside the 24-hour "
                "window since the contact last messaged you.",
                code="template_required",
            )
        if template.status is not TemplateStatus.APPROVED:
            raise SendBlocked(
                f"Template {template.name!r} is {template.status}, not approved.",
                code="template_not_approved",
            )

    # --- conversations -------------------------------------------------

    async def conversation_for(
        self,
        organization_id: uuid.UUID,
        number: str,
        channel: Channel,
        *,
        create: bool = True,
    ) -> Conversation | None:
        found = await self.db.execute(
            select(Conversation).where(
                Conversation.organization_id == organization_id,
                Conversation.channel == channel,
                Conversation.contact_number == number,
            )
        )
        conversation = found.scalars().first()
        if conversation is not None or not create:
            return conversation
        conversation = Conversation(
            organization_id=organization_id, channel=channel, contact_number=number
        )
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    # --- quoting -------------------------------------------------------

    @staticmethod
    def _billable(channel: Channel | str, *, template: bool = False) -> Billable:
        """Which price rule applies.

        Compares by value, not identity. Channel is a StrEnum, so a caller
        that hands over the plain string "sms" -- from a JSON body, a queued
        job, or a column read back raw -- is asking for the same thing. An
        `is` comparison silently fell through to the WhatsApp rule, which
        prices SMS at the wrong rate or, with no WhatsApp rule published, at
        nothing at all.
        """
        if Channel(channel) is Channel.SMS:
            return Billable.SMS_OUTBOUND
        return Billable.WHATSAPP_TEMPLATE if template else Billable.WHATSAPP_OUTBOUND

    async def estimate(
        self,
        *,
        organization_id: uuid.UUID,
        channel: Channel,
        recipients: list[str],
        body: str | None,
        template: MessageTemplate | None = None,
    ) -> SendEstimate:
        """Price a send before it happens, suppressions already deducted."""
        normalised, suppressed = [], 0
        for raw in recipients:
            try:
                number, _ = normalise_number(raw)
            except SendBlocked:
                suppressed += 1
                continue
            if await self.is_suppressed(organization_id, number, channel):
                suppressed += 1
            else:
                normalised.append(number)

        segments = count_segments(body or (template.body if template else ""))
        region = None
        if normalised:
            _, region = normalise_number(normalised[0])

        quote = await self.pricing.quote(
            billable=self._billable(channel, template=template is not None),
            organization_id=organization_id,
            region=region,
            units=Decimal(segments * len(normalised)),
        )
        return SendEstimate(
            recipients=len(recipients),
            suppressed=suppressed,
            segments=segments,
            quote=quote,
        )

    # --- sending -------------------------------------------------------

    async def _existing(self, organization_id: uuid.UUID, key: str | None) -> Message | None:
        if not key:
            return None
        found = await self.db.execute(
            select(Message).where(
                Message.organization_id == organization_id,
                Message.idempotency_key == key,
            )
        )
        return found.scalars().first()

    async def prepare(
        self,
        *,
        organization_id: uuid.UUID,
        channel: Channel,
        to_number: str,
        from_number: str,
        body: str | None = None,
        template: MessageTemplate | None = None,
        template_variables: dict | None = None,
        user_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        lead_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        require_consent: bool = False,
    ) -> Message:
        """Everything up to the provider call: validate, gate, price, persist.

        Returns a message in `QUEUED`, or in `SUPPRESSED` when a gate blocked
        it. Kept separate from dispatch so a campaign can build and price a
        batch without holding a provider connection open.
        """
        if (replay := await self._existing(organization_id, idempotency_key)) is not None:
            log.info("messaging.idempotent_replay", message_id=str(replay.id))
            return replay

        number, region = normalise_number(to_number)
        conversation = await self.conversation_for(organization_id, number, channel)

        message = Message(
            organization_id=organization_id,
            conversation_id=conversation.id if conversation else None,
            campaign_id=campaign_id,
            sent_by_user_id=user_id,
            lead_id=lead_id,
            channel=channel,
            direction=MessageDirection.OUTBOUND,
            from_number=from_number,
            to_number=number,
            region=region,
            body=body or (template.body if template else None),
            template_id=template.id if template else None,
            template_variables=template_variables or {},
            idempotency_key=idempotency_key,
        )

        suppression = await self.is_suppressed(organization_id, number, channel)
        if suppression is not None:
            # Recorded, not dropped: a missing message with no trace is the
            # hardest kind of support question.
            message.status = MessageStatus.SUPPRESSED
            message.suppression_reason = str(suppression.reason)
            self.db.add(message)
            await self.db.commit()
            await self.db.refresh(message)
            return message

        if require_consent and not await self.has_consent(organization_id, number, channel):
            message.status = MessageStatus.SUPPRESSED
            message.suppression_reason = "no_consent"
            self.db.add(message)
            await self.db.commit()
            await self.db.refresh(message)
            return message

        await self._check_template(organization_id, channel, conversation, template)

        message.segments = count_segments(message.body or "")
        quote = await self.pricing.quote(
            billable=self._billable(channel, template=template is not None),
            organization_id=organization_id,
            region=region,
            units=Decimal(message.segments),
        )
        message.customer_charge_usd = quote.charge
        message.price_rule_id = quote.rule_id
        message.cost_incomplete = quote.cost_incomplete
        message.status = MessageStatus.QUEUED
        message.queued_at = datetime.now(UTC)

        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def record_dispatch(
        self,
        message: Message,
        *,
        provider: str,
        provider_message_id: str | None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> Message:
        """Write back what the provider said when we handed the message over."""
        message.provider = provider
        message.provider_message_id = provider_message_id
        if error:
            message.status = MessageStatus.FAILED
            message.error_message = error
            message.error_code = error_code
        else:
            message.status = MessageStatus.SENT
            message.sent_at = datetime.now(UTC)
            if message.conversation_id:
                conversation = await self.db.get(Conversation, message.conversation_id)
                if conversation:
                    conversation.last_message_at = message.sent_at
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def apply_status_update(
        self,
        *,
        provider_message_id: str,
        status: MessageStatus,
        provider_status: str | None = None,
        provider_cost: Decimal | None = None,
        provider_currency: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        """Apply a delivery receipt.

        Receipts arrive out of order and more than once, so a terminal message
        is never moved backwards -- a late `sent` after a `delivered` would
        otherwise undo the delivery.
        """
        found = await self.db.execute(
            select(Message).where(Message.provider_message_id == provider_message_id)
        )
        message = found.scalars().first()
        if message is None:
            return None

        from app.models.messaging import TERMINAL_MESSAGE_STATUSES

        if message.status in TERMINAL_MESSAGE_STATUSES and status not in (MessageStatus.READ,):
            log.info(
                "messaging.late_receipt_ignored",
                message_id=str(message.id),
                had=str(message.status),
                got=str(status),
            )
            return message

        message.status = status
        message.provider_status = provider_status
        if status is MessageStatus.DELIVERED:
            message.delivered_at = datetime.now(UTC)
        elif status is MessageStatus.READ:
            message.read_at = datetime.now(UTC)
        if error_code or error_message:
            message.error_code, message.error_message = error_code, error_message
        if provider_cost is not None:
            message.provider_cost = quantize_cost(abs(to_decimal(provider_cost)))
            message.provider_currency = provider_currency
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def record_inbound(
        self,
        *,
        organization_id: uuid.UUID,
        channel: Channel,
        from_number: str,
        to_number: str,
        body: str,
        provider: str,
        provider_message_id: str,
    ) -> Message:
        """Store an inbound message and open the WhatsApp session window."""
        number, region = normalise_number(from_number)
        conversation = await self.conversation_for(organization_id, number, channel)
        now = datetime.now(UTC)

        message = Message(
            organization_id=organization_id,
            conversation_id=conversation.id if conversation else None,
            channel=channel,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            from_number=number,
            to_number=to_number,
            body=body,
            region=region,
            provider=provider,
            provider_message_id=provider_message_id,
            delivered_at=now,
            # Inbound costs us a fraction of a cent and is not resold.
            customer_charge_usd=ZERO,
        )
        self.db.add(message)
        if conversation is not None:
            conversation.last_message_at = now
            conversation.last_inbound_at = now
            conversation.unread_count = (conversation.unread_count or 0) + 1
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def unread_total(self, organization_id: uuid.UUID) -> int:
        total = await self.db.scalar(
            select(func.coalesce(func.sum(Conversation.unread_count), 0)).where(
                Conversation.organization_id == organization_id,
                Conversation.is_archived.is_(False),
            )
        )
        return int(total or 0)
