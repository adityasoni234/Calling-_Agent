"""Bulk SMS and WhatsApp sends.

A campaign is a queue of individual sends, not a special kind of send. Each
recipient goes through exactly the same gauntlet a one-off message does --
normalise, suppress, consent, template rules, quote -- because a rule that
only applies to single sends is a rule that fails on the day it matters, when
five thousand messages go out at once.

Three things this adds on top:

**A quote before launch.** Nobody should discover the cost of a 5,000-message
campaign from their balance afterwards.

**Pacing.** Carriers rate-limit, and a sender that bursts gets throttled or
flagged. The campaign dispatches in slices.

**Resumability.** Pause, resume and cancel all work mid-flight, and a crashed
worker resumes where it stopped because progress lives in the database rather
than in a loop variable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.money import ZERO, quantize_cost, to_decimal
from app.models.lead import Lead
from app.models.lead_list import LeadListMember
from app.models.messaging import (
    Channel,
    Message,
    MessageCampaign,
    MessageCampaignStatus,
    MessageStatus,
    MessageTemplate,
)
from app.services.messaging.base import MessagingNotConfigured
from app.services.messaging.twilio import get_messaging_provider_async
from app.services.messaging_service import (
    MessagingService,
    SendBlocked,
    normalise_number,
)

log = get_logger(__name__)

#: How many recipients one dispatch pass handles. Small enough that a pause
#: takes effect quickly, large enough not to thrash the database.
SLICE = 50

#: Campaigns that can still be worked on.
LIVE_STATUSES = frozenset({MessageCampaignStatus.SCHEDULED, MessageCampaignStatus.RUNNING})


@dataclass
class Progress:
    total: int
    sent: int
    delivered: int
    failed: int
    suppressed: int
    remaining: int

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        done = self.total - self.remaining
        return min(100, round(done / self.total * 100))


class MessageCampaignService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.messaging = MessagingService(db)

    async def get(self, campaign_id: uuid.UUID, organization_id: uuid.UUID) -> MessageCampaign:
        campaign = await self.db.get(MessageCampaign, campaign_id)
        if campaign is None or campaign.organization_id != organization_id:
            raise NotFoundError("Campaign not found")
        return campaign

    async def recipients_for(
        self, organization_id: uuid.UUID, lead_list_id: uuid.UUID | None
    ) -> list[tuple[uuid.UUID, str]]:
        """Lead ids and phone numbers for a sheet, or the whole book.

        Returns lead ids too, so each message is attributable to the lead it
        was sent about rather than matched back by phone number later.
        """
        query = select(Lead.id, Lead.phone_number).where(
            Lead.organization_id == organization_id,
            Lead.phone_number.isnot(None),
        )
        if lead_list_id is not None:
            query = query.join(LeadListMember, LeadListMember.lead_id == Lead.id).where(
                LeadListMember.lead_list_id == lead_list_id
            )
        rows = await self.db.execute(query)
        return [(lead_id, number) for lead_id, number in rows.all() if number]

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        channel: Channel,
        body: str | None,
        template_id: uuid.UUID | None,
        lead_list_id: uuid.UUID | None,
        from_number: str,
        messages_per_minute: int,
        scheduled_at: datetime | None,
        user_id: uuid.UUID | None,
    ) -> MessageCampaign:
        """Create as a draft, with the recipient count and quote already on it."""
        recipients = await self.recipients_for(organization_id, lead_list_id)
        if not recipients:
            raise AppError("That list has no contactable numbers", code="no_recipients")

        template = None
        if template_id is not None:
            template = await self.db.get(MessageTemplate, template_id)
            if template is None or template.organization_id != organization_id:
                raise NotFoundError("Template not found")

        estimate = await self.messaging.estimate(
            organization_id=organization_id,
            channel=channel,
            recipients=[number for _, number in recipients],
            body=body,
            template=template,
        )

        campaign = MessageCampaign(
            organization_id=organization_id,
            created_by_user_id=user_id,
            name=name,
            channel=channel,
            body=body,
            template_id=template_id,
            lead_list_id=lead_list_id,
            from_number=from_number,
            messages_per_minute=max(1, messages_per_minute),
            scheduled_at=scheduled_at,
            total_recipients=len(recipients),
            estimated_charge_usd=estimate.quote.charge,
            estimated_cost_usd=estimate.quote.provider_cost,
            status=MessageCampaignStatus.DRAFT,
        )
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def launch(self, campaign: MessageCampaign) -> MessageCampaign:
        """Move a draft to running, or to scheduled if it has a future start."""
        if campaign.status not in (
            MessageCampaignStatus.DRAFT,
            MessageCampaignStatus.PAUSED,
        ):
            raise AppError(
                f"A {campaign.status} campaign cannot be launched",
                code="bad_campaign_state",
            )
        now = datetime.now(UTC)
        from app.core.times import as_utc

        scheduled = as_utc(campaign.scheduled_at)
        if scheduled is not None and scheduled > now:
            campaign.status = MessageCampaignStatus.SCHEDULED
        else:
            campaign.status = MessageCampaignStatus.RUNNING
            campaign.started_at = campaign.started_at or now
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def set_status(
        self, campaign: MessageCampaign, status: MessageCampaignStatus
    ) -> MessageCampaign:
        """Pause, resume or cancel.

        Cancelling stops future sends and does not try to recall what has
        already gone out, because a delivered message cannot be unsent and
        pretending otherwise would be worse than saying so.
        """
        campaign.status = status
        if status in (
            MessageCampaignStatus.COMPLETED,
            MessageCampaignStatus.CANCELLED,
        ):
            campaign.finished_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def _already_sent(self, campaign_id: uuid.UUID) -> set[str]:
        rows = await self.db.execute(
            select(Message.to_number).where(Message.campaign_id == campaign_id)
        )
        return set(rows.scalars())

    async def dispatch_slice(self, campaign: MessageCampaign) -> int:
        """Send the next batch. Returns how many were attempted.

        Idempotent per recipient: the campaign id plus the number form the
        idempotency key, so a crashed worker that re-runs a slice cannot send
        anyone a second copy.
        """
        if campaign.status is not MessageCampaignStatus.RUNNING:
            return 0

        recipients = await self.recipients_for(campaign.organization_id, campaign.lead_list_id)
        done = await self._already_sent(campaign.id)

        template = None
        if campaign.template_id:
            template = await self.db.get(MessageTemplate, campaign.template_id)

        provider = await get_messaging_provider_async()
        attempted = 0

        for lead_id, raw in recipients:
            if attempted >= SLICE:
                break
            try:
                number, _ = normalise_number(raw)
            except SendBlocked:
                # An unusable number in a 5,000-row sheet is not a reason to
                # abandon the campaign; it is skipped and counted.
                campaign.suppressed_count += 1
                continue
            if number in done:
                continue

            attempted += 1
            try:
                message = await self.messaging.prepare(
                    organization_id=campaign.organization_id,
                    channel=campaign.channel,
                    to_number=number,
                    from_number=campaign.from_number or "",
                    body=campaign.body,
                    template=template,
                    campaign_id=campaign.id,
                    lead_id=lead_id,
                    idempotency_key=f"campaign:{campaign.id}:{number}",
                )
            except SendBlocked as exc:
                # A template or validation failure is about the campaign, not
                # this recipient. Stop rather than burning the whole list.
                log.warning("campaign.blocked", campaign_id=str(campaign.id), error=str(exc))
                await self.set_status(campaign, MessageCampaignStatus.FAILED)
                break

            if message.status is MessageStatus.SUPPRESSED:
                campaign.suppressed_count += 1
                continue
            if message.status is not MessageStatus.QUEUED:
                continue  # an idempotent replay; already handled

            try:
                result = await provider.send(
                    to_number=message.to_number,
                    from_number=message.from_number,
                    body=message.body,
                    channel=message.channel,
                )
            except MessagingNotConfigured as exc:
                await self.messaging.record_dispatch(
                    message,
                    provider=provider.name,
                    provider_message_id=None,
                    error=str(exc),
                    error_code="provider_unconfigured",
                )
                await self.set_status(campaign, MessageCampaignStatus.FAILED)
                break

            await self.messaging.record_dispatch(
                message,
                provider=provider.name,
                provider_message_id=result.provider_message_id,
                error=result.error_message,
                error_code=result.error_code,
            )
            if result.accepted:
                campaign.sent_count += 1
            else:
                campaign.failed_count += 1

        await self.db.commit()
        await self.refresh_progress(campaign)
        return attempted

    async def refresh_progress(self, campaign: MessageCampaign) -> Progress:
        """Recount from the messages themselves.

        The counters on the campaign are a cache for listing. Delivery
        receipts arrive long after a send, so the authoritative numbers come
        from the message rows and the cache is corrected from them.
        """
        rows = await self.db.execute(
            select(Message.status, func.count())
            .where(Message.campaign_id == campaign.id)
            .group_by(Message.status)
        )
        counts = {str(status): int(count) for status, count in rows.all()}
        delivered = counts.get("delivered", 0) + counts.get("read", 0)
        sent = counts.get("sent", 0) + delivered + counts.get("undelivered", 0)
        failed = counts.get("failed", 0)
        suppressed = counts.get("suppressed", 0)
        handled = sent + failed + suppressed

        campaign.sent_count = sent
        campaign.delivered_count = delivered
        campaign.failed_count = failed
        campaign.suppressed_count = suppressed

        charged = await self.db.scalar(
            select(func.coalesce(func.sum(Message.customer_charge_usd), 0)).where(
                Message.campaign_id == campaign.id
            )
        )
        campaign.actual_charge_usd = quantize_cost(to_decimal(charged) or ZERO)

        remaining = max(0, campaign.total_recipients - handled)
        if remaining == 0 and campaign.status is MessageCampaignStatus.RUNNING:
            campaign.status = MessageCampaignStatus.COMPLETED
            campaign.finished_at = datetime.now(UTC)
        await self.db.commit()

        return Progress(
            total=campaign.total_recipients,
            sent=sent,
            delivered=delivered,
            failed=failed,
            suppressed=suppressed,
            remaining=remaining,
        )

    async def due(self) -> list[MessageCampaign]:
        """Campaigns a worker should act on now."""
        from app.core.times import as_utc

        rows = await self.db.execute(
            select(MessageCampaign).where(MessageCampaign.status.in_(LIVE_STATUSES))
        )
        now = datetime.now(UTC)
        out = []
        for campaign in rows.scalars():
            scheduled = as_utc(campaign.scheduled_at)
            if campaign.status is MessageCampaignStatus.RUNNING:
                out.append(campaign)
            elif scheduled is None or scheduled <= now:
                out.append(campaign)
        return out
