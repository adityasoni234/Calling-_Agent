"""Sending email, and the rules that stop you sending the wrong thing.

Every send passes the same gauntlet as a campaign of fifty thousand,
because a rule that only applies to bulk is a rule that fails the first
time someone loops over the single-send endpoint.

The order is deliberate:

1. **Normalise and validate** -- the verdict decides eligibility, and it is
   recorded on the message so "why did you mail that address?" is answerable
   from the row rather than reconstructed.
2. **Suppression** -- hard bounces, complaints and unsubscribes. No campaign
   setting may override it.
3. **Quote** through the price book.
4. **Dispatch**, then record what the provider said.

A hard bounce suppresses the address immediately on the way back in. That
is the single most important behaviour here: sending again after one is how
a sending domain gets blocked, and by then it is not quickly undone.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.money import quantize_cost, to_decimal
from app.models.email import (
    NEVER_SEND,
    TERMINAL_EMAIL_STATUSES,
    EmailAddress,
    EmailCampaign,
    EmailCampaignStatus,
    EmailMessage,
    EmailStatus,
    EmailSuppression,
    EmailSuppressionReason,
    EmailVerdict,
)
from app.models.price_book import Billable
from app.services.email.base import EmailNotConfigured, OutboundEmail
from app.services.email.smtp import get_email_provider
from app.services.email_validation import EmailValidator, normalise
from app.services.pricing_engine import PricingEngine, Quote

log = get_logger(__name__)

#: How many a dispatch pass handles. Small enough that a pause takes effect
#: promptly, large enough not to thrash the database.
SLICE = 50


class EmailBlocked(AppError):
    def __init__(self, message: str, *, code: str = "email_blocked") -> None:
        super().__init__(message, code=code)


@dataclass
class CampaignPlan:
    """What a campaign will do, before anyone approves it."""

    total: int
    valid: int
    risky: int
    invalid: int
    suppressed: int
    unknown: int
    eligible: int
    quote: Quote

    def as_dict(self) -> dict:
        return {
            "total_recipients": self.total,
            "valid": self.valid,
            "risky": self.risky,
            "invalid": self.invalid,
            "suppressed": self.suppressed,
            "unknown": self.unknown,
            "eligible": self.eligible,
            **self.quote.as_dict(),
        }


class EmailService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.validator = EmailValidator(db)
        self.pricing = PricingEngine(db)

    # --- suppression ---------------------------------------------------

    async def suppress(
        self,
        organization_id: uuid.UUID,
        address: str,
        *,
        reason: EmailSuppressionReason,
        detail: str | None = None,
        source_message_id: uuid.UUID | None = None,
    ) -> EmailSuppression:
        """Block an address permanently. Idempotent.

        Suppressing twice is normal -- a bounce webhook can arrive more than
        once -- and must not raise.
        """
        address = normalise(address)
        found = await self.db.execute(
            select(EmailSuppression).where(
                EmailSuppression.organization_id == organization_id,
                EmailSuppression.address == address,
            )
        )
        existing = found.scalars().first()
        if existing is not None:
            return existing

        suppression = EmailSuppression(
            organization_id=organization_id,
            address=address,
            reason=reason,
            detail=detail,
            source_message_id=source_message_id,
        )
        self.db.add(suppression)

        # Keep the cached verdict honest, or a later validation pass would
        # report the address as valid while the suppression still blocks it.
        cached = await self.db.execute(
            select(EmailAddress).where(
                EmailAddress.organization_id == organization_id,
                EmailAddress.address == address,
            )
        )
        if (row := cached.scalars().first()) is not None:
            row.verdict = EmailVerdict.SUPPRESSED
            row.reason = f"Suppressed: {str(reason).replace('_', ' ')}"
            if reason is EmailSuppressionReason.HARD_BOUNCE:
                row.bounce_count = (row.bounce_count or 0) + 1

        await self.db.commit()
        await self.db.refresh(suppression)
        log.info("email.suppressed", reason=str(reason))
        return suppression

    async def unsubscribe_by_token(self, token: str) -> EmailMessage | None:
        """Honour an unsubscribe link without needing the address in the URL."""
        found = await self.db.execute(
            select(EmailMessage).where(EmailMessage.unsubscribe_token == token)
        )
        message = found.scalars().first()
        if message is None:
            return None
        await self.suppress(
            message.organization_id,
            message.to_address,
            reason=EmailSuppressionReason.UNSUBSCRIBED,
            detail="Clicked the unsubscribe link",
            source_message_id=message.id,
        )
        if message.status not in TERMINAL_EMAIL_STATUSES:
            message.status = EmailStatus.UNSUBSCRIBED
            await self.db.commit()
        return message

    # --- sending -------------------------------------------------------

    def _unsubscribe_url(self, token: str) -> str | None:
        base = settings.email_public_base_url or settings.public_base_url
        return f"{base}/api/v1/email/unsubscribe/{token}" if base else None

    async def prepare(
        self,
        *,
        organization_id: uuid.UUID,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        from_address: str = "",
        from_name: str = "",
        reply_to: str | None = None,
        campaign_id: uuid.UUID | None = None,
        lead_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        allow_risky: bool = False,
        check_dns: bool = True,
    ) -> EmailMessage:
        """Validate, gate, price and persist. Does not dispatch."""
        if idempotency_key:
            replay = await self.db.execute(
                select(EmailMessage).where(
                    EmailMessage.organization_id == organization_id,
                    EmailMessage.idempotency_key == idempotency_key,
                )
            )
            if (found := replay.scalars().first()) is not None:
                return found

        address = normalise(to_address)
        verdict = await self.validator.validate_one(organization_id, address, check_dns=check_dns)

        message = EmailMessage(
            organization_id=organization_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            sent_by_user_id=user_id,
            to_address=address,
            from_address=from_address,
            subject=subject,
            verdict_at_send=str(verdict.verdict),
            idempotency_key=idempotency_key,
            unsubscribe_token=secrets.token_urlsafe(24),
        )

        blocked = verdict.verdict in NEVER_SEND or (
            verdict.verdict is EmailVerdict.RISKY and not allow_risky
        )
        if blocked:
            # Recorded, not dropped. A missing email with no trace is the
            # hardest support question there is.
            message.status = EmailStatus.BLOCKED
            message.error_code = str(verdict.verdict)
            message.error_message = verdict.reason
            self.db.add(message)
            await self.db.commit()
            await self.db.refresh(message)
            return message

        quote = await self.pricing.quote(
            billable=Billable.EMAIL_OUTBOUND,
            organization_id=organization_id,
            units=Decimal(1),
        )

        message.status = EmailStatus.QUEUED
        message.queued_at = datetime.now(UTC)
        message.customer_charge_usd = quote.charge
        message.price_rule_id = quote.rule_id
        message.cost_incomplete = quote.cost_incomplete
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def dispatch(
        self, message: EmailMessage, *, campaign: EmailCampaign | None = None
    ) -> EmailMessage:
        """Hand a queued message to the provider and record the outcome."""
        if message.status is not EmailStatus.QUEUED:
            return message

        provider = await get_email_provider(message.organization_id, self.db)
        try:
            result = await provider.send(
                OutboundEmail(
                    to_address=message.to_address,
                    subject=message.subject,
                    text_body=(campaign.text_body if campaign else "") or " ",
                    html_body=campaign.html_body if campaign else None,
                    from_address=message.from_address,
                    from_name=(campaign.from_name if campaign else ""),
                    reply_to=campaign.reply_to if campaign else None,
                    unsubscribe_url=self._unsubscribe_url(message.unsubscribe_token or ""),
                )
            )
        except EmailNotConfigured as exc:
            message.status = EmailStatus.FAILED
            message.error_code = "provider_unconfigured"
            message.error_message = str(exc)
            await self.db.commit()
            return message

        message.provider = provider.name
        message.provider_message_id = result.provider_message_id
        if result.accepted:
            message.status = EmailStatus.SENT
            message.sent_at = datetime.now(UTC)
        else:
            message.status = EmailStatus.FAILED
            message.error_code = result.error_code
            message.error_message = result.error_message
            # A refused recipient is the address's fault and permanent; a
            # transport error is ours and must not suppress anyone.
            if result.error_code == "recipient_refused":
                await self.suppress(
                    message.organization_id,
                    message.to_address,
                    reason=EmailSuppressionReason.HARD_BOUNCE,
                    detail=result.error_message,
                    source_message_id=message.id,
                )
        await self.db.commit()
        await self.db.refresh(message)
        return message

    # --- events --------------------------------------------------------

    async def apply_event(
        self,
        *,
        provider_message_id: str,
        status: str,
        detail: str | None = None,
        permanent: bool = False,
    ) -> EmailMessage | None:
        """Apply a provider event, suppressing on anything permanent."""
        found = await self.db.execute(
            select(EmailMessage).where(EmailMessage.provider_message_id == provider_message_id)
        )
        message = found.scalars().first()
        if message is None:
            return None

        try:
            new_status = EmailStatus(status)
        except ValueError:
            return message

        # Never move a terminal message backwards. Events arrive out of
        # order, and a late "delivered" after a bounce would un-bounce it.
        if message.status in TERMINAL_EMAIL_STATUSES:
            return message

        message.status = new_status
        now = datetime.now(UTC)
        if new_status is EmailStatus.DELIVERED:
            message.delivered_at = now
        elif new_status is EmailStatus.OPENED:
            message.opened_at = now
        elif new_status is EmailStatus.CLICKED:
            message.clicked_at = now
        if detail:
            message.error_message = detail
        await self.db.commit()

        if permanent:
            reason = {
                EmailStatus.BOUNCED: EmailSuppressionReason.HARD_BOUNCE,
                EmailStatus.COMPLAINED: EmailSuppressionReason.COMPLAINT,
                EmailStatus.UNSUBSCRIBED: EmailSuppressionReason.UNSUBSCRIBED,
            }.get(new_status, EmailSuppressionReason.MANUAL)
            await self.suppress(
                message.organization_id,
                message.to_address,
                reason=reason,
                detail=detail,
                source_message_id=message.id,
            )
        await self.db.refresh(message)
        return message

    # --- campaigns -----------------------------------------------------

    async def plan(
        self, campaign: EmailCampaign, addresses: list[str], *, check_dns: bool = True
    ) -> CampaignPlan:
        """Validate a list and quote it, before anyone presses send."""
        batch = await self.validator.validate_batch(
            campaign.organization_id, addresses, check_dns=check_dns
        )
        await self.validator.persist(campaign.organization_id, batch.results)
        summary = batch.summary

        eligible = summary["valid"] + (summary["risky"] if campaign.include_risky else 0)
        quote = await self.pricing.quote(
            billable=Billable.EMAIL_OUTBOUND,
            organization_id=campaign.organization_id,
            units=Decimal(eligible),
        )

        campaign.total_recipients = summary["total"]
        campaign.valid_count = summary["valid"]
        campaign.risky_count = summary["risky"]
        campaign.invalid_count = summary["invalid"]
        campaign.suppressed_count = summary["suppressed"]
        campaign.unknown_count = summary["unknown"]
        campaign.validated_at = datetime.now(UTC)
        campaign.estimated_charge_usd = quote.charge
        campaign.status = EmailCampaignStatus.READY
        await self.db.commit()
        await self.db.refresh(campaign)

        return CampaignPlan(
            total=summary["total"],
            valid=summary["valid"],
            risky=summary["risky"],
            invalid=summary["invalid"],
            suppressed=summary["suppressed"],
            unknown=summary["unknown"],
            eligible=eligible,
            quote=quote,
        )

    async def refresh_campaign(self, campaign: EmailCampaign) -> EmailCampaign:
        """Recount from the messages themselves.

        The counters are a cache for listing; events arrive long after a
        send, so the authoritative numbers come from the message rows.
        """
        rows = await self.db.execute(
            select(EmailMessage.status, func.count())
            .where(EmailMessage.campaign_id == campaign.id)
            .group_by(EmailMessage.status)
        )
        counts = {str(s): int(c) for s, c in rows.all()}
        campaign.delivered_count = counts.get("delivered", 0)
        campaign.opened_count = counts.get("opened", 0)
        campaign.clicked_count = counts.get("clicked", 0)
        campaign.bounced_count = counts.get("bounced", 0)
        campaign.complained_count = counts.get("complained", 0)
        campaign.unsubscribed_count = counts.get("unsubscribed", 0)
        campaign.sent_count = sum(
            counts.get(k, 0)
            for k in ("sent", "delivered", "opened", "clicked", "bounced", "complained")
        )

        charged = await self.db.scalar(
            select(func.coalesce(func.sum(EmailMessage.customer_charge_usd), 0)).where(
                EmailMessage.campaign_id == campaign.id
            )
        )
        campaign.actual_charge_usd = quantize_cost(to_decimal(charged))
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign
