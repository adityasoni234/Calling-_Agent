"""Campaign dispatch with hard concurrency limits.

Concurrency is counted from the calls table rather than held in memory, so a
restart or a second worker can never double-dial. Uncontrolled parallel dialing
is both a cost incident and a compliance incident.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.models.call import Call, CallStatus
from app.models.campaign import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from app.models.lead import Lead, LeadStatus
from app.services.call_service import CallService
from app.services.cost_service import CostService

log = get_logger(__name__)

ACTIVE_CALL_STATUSES = (CallStatus.INITIATED, CallStatus.RINGING, CallStatus.IN_PROGRESS)
# A busy or unanswered number is worth retrying; a wrong number is not.
RETRYABLE_STATUSES = (CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED)


class CampaignService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, campaign_id: uuid.UUID, organization_id: uuid.UUID) -> Campaign:
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None or campaign.organization_id != organization_id:
            raise NotFoundError("Campaign not found")
        return campaign

    async def add_leads(self, campaign: Campaign, lead_ids: list[uuid.UUID]) -> int:
        existing = await self.db.execute(
            select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id)
        )
        already = set(existing.scalars())
        added = 0
        for lead_id in lead_ids:
            if lead_id in already:
                continue
            self.db.add(CampaignLead(campaign_id=campaign.id, lead_id=lead_id))
            added += 1
        await self.db.commit()
        return added

    async def set_status(self, campaign: Campaign, status: CampaignStatus) -> Campaign:
        if campaign.status is CampaignStatus.COMPLETED:
            raise AppError("Campaign has already completed", code="campaign_completed")

        if status is CampaignStatus.RUNNING:
            total = await self.db.scalar(
                select(func.count())
                .select_from(CampaignLead)
                .where(CampaignLead.campaign_id == campaign.id)
            )
            if not total:
                raise AppError("Add leads before starting the campaign", code="campaign_empty")
            campaign.started_at = campaign.started_at or datetime.now(UTC)
        if status in {CampaignStatus.COMPLETED, CampaignStatus.STOPPED}:
            campaign.completed_at = datetime.now(UTC)

        campaign.status = status
        await self.db.commit()
        await self.db.refresh(campaign)
        log.info("campaign.status", campaign_id=str(campaign.id), status=status.value)
        return campaign

    # --- dispatch ------------------------------------------------------

    def within_calling_hours(self, campaign: Campaign, now: datetime | None = None) -> bool:
        try:
            zone = ZoneInfo(campaign.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        local = (now or datetime.now(UTC)).astimezone(zone).time()
        start, end = campaign.calling_hours_start, campaign.calling_hours_end
        if start <= end:
            return start <= local <= end
        # Window wrapping midnight.
        return local >= start or local <= end

    async def active_call_count(self, campaign_id: uuid.UUID) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(Call)
                .where(Call.campaign_id == campaign_id, Call.status.in_(ACTIVE_CALL_STATUSES))
            )
            or 0
        )

    async def global_active_calls(self, organization_id: uuid.UUID) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(Call)
                .where(
                    Call.organization_id == organization_id,
                    Call.status.in_(ACTIVE_CALL_STATUSES),
                )
            )
            or 0
        )

    async def dispatch(self, campaign_id: uuid.UUID) -> dict[str, int | str]:
        """One dispatch tick. Returns what it did and why it stopped."""
        campaign = await self.db.get(Campaign, campaign_id)
        if campaign is None:
            return {"started": 0, "reason": "not_found"}
        if campaign.status is not CampaignStatus.RUNNING:
            return {"started": 0, "reason": f"status_{campaign.status.value}"}
        if not self.within_calling_hours(campaign):
            return {"started": 0, "reason": "outside_calling_hours"}

        allowed, budget_reason = await CostService(self.db).can_start_call(campaign.organization_id)
        if not allowed:
            await self.set_status(campaign, CampaignStatus.PAUSED)
            return {"started": 0, "reason": budget_reason or "budget_exceeded"}
        if campaign.budget_limit_usd:
            spent = float(
                await self.db.scalar(
                    select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(
                        Call.campaign_id == campaign.id
                    )
                )
                or 0.0
            )
            if spent >= campaign.budget_limit_usd:
                await self.set_status(campaign, CampaignStatus.PAUSED)
                return {"started": 0, "reason": "campaign_budget_reached"}

        in_flight = await self.active_call_count(campaign.id)
        slots = min(
            campaign.max_concurrent_calls - in_flight,
            settings.max_global_concurrent_calls
            - await self.global_active_calls(campaign.organization_id),
        )
        if slots <= 0:
            return {"started": 0, "reason": "at_concurrency_limit"}

        due = await self._due_leads(campaign, limit=slots)
        if not due:
            if await self._is_exhausted(campaign):
                await self.set_status(campaign, CampaignStatus.COMPLETED)
                return {"started": 0, "reason": "completed"}
            return {"started": 0, "reason": "nothing_due"}

        service = CallService(self.db)
        started = 0
        for membership, lead in due:
            membership.status = CampaignLeadStatus.DIALING
            membership.attempts += 1
            membership.last_attempt_at = datetime.now(UTC)
            await self.db.commit()

            call = await service.create_and_originate(
                organization_id=campaign.organization_id,
                agent_id=campaign.agent_id,
                lead_id=lead.id,
                campaign_id=campaign.id,
            )
            if call.status is CallStatus.FAILED:
                await self.on_call_finished(call)
            else:
                started += 1

        return {"started": started, "reason": "dispatched"}

    async def _due_leads(
        self, campaign: Campaign, *, limit: int
    ) -> list[tuple[CampaignLead, Lead]]:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(CampaignLead, Lead)
            .join(Lead, Lead.id == CampaignLead.lead_id)
            .where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.status == CampaignLeadStatus.PENDING,
                Lead.status != LeadStatus.DO_NOT_CALL,
            )
            .order_by(CampaignLead.next_attempt_at.is_(None).desc(), CampaignLead.next_attempt_at)
            .limit(limit * 3)
        )
        due: list[tuple[CampaignLead, Lead]] = []
        for membership, lead in result.all():
            if (
                membership.next_attempt_at
                and membership.next_attempt_at.replace(
                    tzinfo=membership.next_attempt_at.tzinfo or UTC
                )
                > now
            ):
                continue
            due.append((membership, lead))
            if len(due) >= limit:
                break
        return due

    async def _is_exhausted(self, campaign: Campaign) -> bool:
        remaining = await self.db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.status.in_([CampaignLeadStatus.PENDING, CampaignLeadStatus.DIALING]),
            )
        )
        return not remaining

    async def on_call_finished(self, call: Call) -> None:
        """Mark the membership done, or schedule a retry within the cap."""
        if not call.campaign_id or not call.lead_id:
            return
        result = await self.db.execute(
            select(CampaignLead).where(
                CampaignLead.campaign_id == call.campaign_id,
                CampaignLead.lead_id == call.lead_id,
            )
        )
        membership = result.scalars().first()
        if membership is None:
            return
        campaign = await self.db.get(Campaign, call.campaign_id)
        if campaign is None:
            return

        if call.status is CallStatus.COMPLETED:
            membership.status = CampaignLeadStatus.COMPLETED
        elif call.status in RETRYABLE_STATUSES and membership.attempts <= campaign.max_retries:
            membership.status = CampaignLeadStatus.PENDING
            membership.next_attempt_at = datetime.now(UTC) + timedelta(
                minutes=campaign.retry_delay_minutes
            )
        else:
            membership.status = (
                CampaignLeadStatus.EXHAUSTED
                if membership.attempts > campaign.max_retries
                else CampaignLeadStatus.FAILED
            )
        await self.db.commit()
