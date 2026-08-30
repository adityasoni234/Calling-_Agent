"""Call lifecycle: originate, track provider webhooks, finalise."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.models.agent import Agent
from app.models.call import (
    TERMINAL_STATUSES,
    Call,
    CallDirection,
    CallStatus,
    CallTurn,
)
from app.models.lead import Lead
from app.services.base import ProviderError
from app.services.cost_service import CostService
from app.services.registry import get_telephony
from app.services.telephony import urls
from app.services.telephony.base import TelephonyEvent
from app.services.telephony.region import region_of

log = get_logger(__name__)


class CallService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _urls(self, call_id: uuid.UUID, provider: str) -> tuple[str, str, str]:
        return (
            urls.answer_url(provider, call_id),
            urls.status_url(provider, call_id),
            urls.media_url(call_id),
        )

    async def create_and_originate(
        self,
        *,
        organization_id: uuid.UUID,
        agent_id: uuid.UUID,
        lead_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        to_number: str | None = None,
        from_number: str | None = None,
    ) -> Call:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != organization_id:
            raise NotFoundError("Agent not found")

        lead: Lead | None = None
        if lead_id:
            lead = await self.db.get(Lead, lead_id)
            if lead is None or lead.organization_id != organization_id:
                raise NotFoundError("Lead not found")

        destination = to_number or (lead.phone_number if lead else None)
        if not destination:
            raise AppError("No phone number to call", code="missing_phone_number")

        allowed, reason = await CostService(self.db).can_start_call(organization_id)
        if not allowed:
            raise AppError(
                reason or "Budget limit reached", code="budget_exceeded", status_code=402
            )

        provider = get_telephony()
        caller_id = from_number or self._default_caller_id(provider.name)

        call = Call(
            organization_id=organization_id,
            agent_id=agent_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            direction=CallDirection.OUTBOUND,
            provider=provider.name,
            from_number=caller_id,
            to_number=destination,
            status=CallStatus.INITIATED,
            started_at=datetime.now(UTC),
        )
        self.db.add(call)
        await self.db.commit()
        await self.db.refresh(call)

        answer_url, status_url, _ = self._urls(call.id, provider.name)
        try:
            result = await provider.originate(
                to_number=destination,
                from_number=caller_id,
                answer_url=answer_url,
                status_url=status_url,
                call_id=str(call.id),
                record=agent.record_calls,
            )
            call.provider_call_id = result.provider_call_id
            call.status = result.status
        except ProviderError as exc:
            call.status = CallStatus.FAILED
            call.error = str(exc)
            call.ended_at = datetime.now(UTC)
            log.error("call.originate_failed", call_id=str(call.id), error=str(exc))

        if lead:
            lead.call_count += 1
            lead.last_called_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(call)
        return call

    @staticmethod
    def _default_caller_id(provider_name: str) -> str:
        return {
            "plivo": settings.plivo_caller_id,
            "twilio": settings.twilio_caller_id,
            "telnyx": settings.telnyx_caller_id,
        }.get(provider_name, "+10000000000")

    async def accept_inbound(
        self, *, provider: str, provider_call_id: str, from_number: str, to_number: str
    ) -> Call | None:
        """Create a call record for someone dialling in, and pick up.

        The agent is chosen by `INBOUND_AGENT_ID`, falling back to the first
        active agent -- a single-agent deployment should not need configuration
        to answer its own phone.
        """
        agent = None
        if settings.inbound_agent_id:
            with contextlib.suppress(ValueError):
                agent = await self.db.get(Agent, uuid.UUID(settings.inbound_agent_id))
        if agent is None:
            result = await self.db.execute(
                select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.created_at).limit(1)
            )
            agent = result.scalars().first()
        if agent is None:
            log.warning("call.inbound_no_agent", provider_call_id=provider_call_id)
            return None

        # Match the caller to an existing lead so the call joins their history.
        lead = None
        if from_number:
            result = await self.db.execute(
                select(Lead).where(
                    Lead.organization_id == agent.organization_id,
                    Lead.phone_number == from_number,
                )
            )
            lead = result.scalars().first()

        call = Call(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            lead_id=lead.id if lead else None,
            direction=CallDirection.INBOUND,
            provider=provider,
            provider_call_id=provider_call_id,
            from_number=from_number,
            to_number=to_number,
            status=CallStatus.RINGING,
            started_at=datetime.now(UTC),
        )
        self.db.add(call)
        await self.db.commit()
        await self.db.refresh(call)
        log.info("call.inbound", call_id=str(call.id), from_number=from_number, agent=agent.name)
        return call

    async def by_provider_call_id(self, provider_call_id: str) -> Call | None:
        result = await self.db.execute(
            select(Call).where(Call.provider_call_id == provider_call_id)
        )
        return result.scalars().first()

    async def apply_event(self, call: Call, event: TelephonyEvent) -> Call:
        """Advance the call from a provider webhook. Terminal states are final."""
        if call.status in TERMINAL_STATUSES:
            return call

        if event.provider_call_id and not call.provider_call_id:
            call.provider_call_id = event.provider_call_id

        if event.status:
            call.status = event.status
        if event.status is CallStatus.IN_PROGRESS and call.answered_at is None:
            call.answered_at = datetime.now(UTC)
        if event.recording_url:
            call.recording_url = event.recording_url
        if event.hangup_cause:
            call.end_reason = call.end_reason or event.hangup_cause

        if event.status in TERMINAL_STATUSES:
            await self._finalize(call, duration_seconds=event.duration_seconds)

        await self.db.commit()
        await self.db.refresh(call)
        return call

    async def _finalize(self, call: Call, *, duration_seconds: int | None = None) -> None:
        call.ended_at = call.ended_at or datetime.now(UTC)
        if duration_seconds is not None:
            call.duration_seconds = duration_seconds
        elif call.answered_at:
            call.duration_seconds = max(0, int((call.ended_at - call.answered_at).total_seconds()))

        if call.duration_seconds > 0:
            provider = get_telephony(call.provider)
            await CostService(self.db).record_usage(
                call=call,
                records=[
                    provider.usage_for_call(call.duration_seconds, region=region_of(call.to_number))
                ],
                commit=False,
            )

    async def end_call(self, call: Call, *, reason: str = "hangup") -> Call:
        if call.provider_call_id and call.status not in TERMINAL_STATUSES:
            try:
                await get_telephony(call.provider).hangup(call.provider_call_id)
            except ProviderError as exc:
                log.warning("call.hangup_failed", call_id=str(call.id), error=str(exc))

        call.status = CallStatus.COMPLETED if call.answered_at else CallStatus.CANCELED
        call.end_reason = reason
        await self._finalize(call)
        await self.db.commit()
        await self.db.refresh(call)
        return call

    async def transfer(self, call: Call, to_number: str) -> None:
        if not call.provider_call_id:
            raise AppError("Call has no provider id yet", code="not_transferable")
        await get_telephony(call.provider).transfer(call.provider_call_id, to_number)
        call.end_reason = "transferred"
        await self.db.commit()

    async def save_turns(self, call_id: uuid.UUID, turns: list[dict]) -> None:
        result = await self.db.execute(
            select(func.coalesce(func.max(CallTurn.turn_index), -1)).where(
                CallTurn.call_id == call_id
            )
        )
        index = int(result.scalar_one()) + 1
        for offset, turn in enumerate(turns):
            self.db.add(
                CallTurn(
                    call_id=call_id,
                    turn_index=index + offset,
                    role=turn["role"],
                    content=turn["content"],
                    state=turn.get("state"),
                    latency_ms=turn.get("latency_ms"),
                    barge_in=bool(turn.get("barge_in")),
                    spoken_at=datetime.now(UTC),
                )
            )
        await self.db.commit()
