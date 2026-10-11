"""Credits: the commercial layer between what a call costs us and what it sells for.

One credit is one US cent of list price. That keeps the arithmetic obvious to
everyone -- a customer sees "1,500 credits left", support sees $15.00, and
nobody has to reason about an invented currency with a floating conversion.

Provider cost and customer price are kept separate on purpose. The margin is
then a fact recorded on every usage entry rather than something recomputed
later from rates that may since have changed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import CreditEntry, CreditEntryKind
from app.models.call import Call
from app.models.organization import Organization
from app.models.reservation import CreditReservation, ReservationStatus

log = get_logger(__name__)

#: One credit == one US cent of list price.
CREDITS_PER_USD = 100.0
#: Charged even for a call that connects and ends immediately: the carrier bills
#: us for the attempt, so a free zero-second call would be a loss.
MINIMUM_CALL_CREDITS = 1.0
#: What we hold before dialling, as minutes of a typical call. Generous on
#: purpose: a hold that runs out mid-conversation is worse than one that ties
#: up a few credits for ninety seconds.
RESERVE_MINUTES = 3.0
#: A held reservation whose call never reported a terminal state is released
#: after this long, so a dropped webhook cannot freeze credits forever.
RESERVATION_TTL_MINUTES = 30


class InsufficientCredits(Exception):
    """Raised when a call cannot be afforded. Carries the numbers for the message."""

    def __init__(self, balance: float, needed: float) -> None:
        self.balance = balance
        self.needed = needed
        super().__init__(f"balance {balance:.0f}, needs about {needed:.0f}")


def spend_total(ledger_sum: float) -> float:
    """Turn a sum of usage ledger entries into a positive spend figure.

    Usage is stored as a negative amount, so spend is the negated sum. Negating
    a zero sum yields -0.0, which renders as "-0.00" on an account that has
    never placed a call; adding zero normalises the sign.
    """
    return round(-ledger_sum + 0.0, 2)


class BillingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- reading -------------------------------------------------------

    async def balance(self, organization_id: uuid.UUID) -> float:
        organization = await self.db.get(Organization, organization_id)
        return float(organization.credit_balance) if organization else 0.0

    async def ledger_total(self, organization_id: uuid.UUID) -> float:
        """Recompute from the ledger. The cached balance must agree with this."""
        total = await self.db.scalar(
            select(func.coalesce(func.sum(CreditEntry.amount), 0.0)).where(
                CreditEntry.organization_id == organization_id
            )
        )
        return float(total or 0.0)

    def credits_for(self, cost_usd: float) -> float:
        """What we charge for a call that cost us `cost_usd`.

        A markup on provider cost rather than a per-minute price: telephony to
        the UK costs six times India, and a flat per-minute price would either
        lose money on one or be uncompetitive on the other.
        """
        marked_up = cost_usd * settings.credit_markup_multiplier
        return max(MINIMUM_CALL_CREDITS, round(marked_up * CREDITS_PER_USD, 2))

    async def held_credits(self, organization_id: uuid.UUID) -> float:
        """Credits set aside for calls currently in flight."""
        total = await self.db.scalar(
            select(func.coalesce(func.sum(CreditReservation.amount), 0.0)).where(
                CreditReservation.organization_id == organization_id,
                CreditReservation.status == ReservationStatus.HELD,
            )
        )
        return round(float(total or 0.0), 2)

    async def spendable(self, organization_id: uuid.UUID) -> float:
        """Balance minus what in-flight calls have already claimed.

        This is the number every spend decision must use. Reading the raw
        balance is what let twenty concurrent calls each see ten credits.
        """
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            return 0.0
        return round(organization.credit_balance - await self.held_credits(organization_id), 2)

    # --- the gate ------------------------------------------------------

    async def can_afford_call(self, organization_id: uuid.UUID) -> tuple[bool, str | None]:
        """Checked before a call is placed.

        Deliberately conservative: it refuses when the balance would not cover a
        short call, because stopping before dialling is far better than cutting
        a live conversation off mid-sentence.
        """
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            return False, "Organization not found"
        if organization.is_suspended:
            return False, organization.suspended_reason or "This account is suspended"

        floor = -abs(organization.credit_overdraft)
        # Spendable, not balance: credits already promised to a live call are
        # not available to start another one.
        available = await self.spendable(organization_id)
        if available <= floor:
            held = await self.held_credits(organization_id)
            detail = f" ({held:.0f} held for calls in progress)" if held else ""
            return False, (
                f"Out of credits. {available:.0f} available{detail}. Top up to keep calling."
            )
        return True, None

    # --- writing -------------------------------------------------------

    async def _append(
        self,
        organization: Organization,
        *,
        kind: CreditEntryKind,
        amount: float,
        call_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        note: str | None = None,
        provider_cost_usd: float | None = None,
    ) -> CreditEntry:
        """Append one movement and move the cached balance with it."""
        organization.credit_balance = round(organization.credit_balance + amount, 2)
        entry = CreditEntry(
            organization_id=organization.id,
            kind=kind,
            amount=round(amount, 2),
            balance_after=organization.credit_balance,
            call_id=call_id,
            actor_user_id=actor_user_id,
            note=note,
            provider_cost_usd=provider_cost_usd,
        )
        self.db.add(entry)
        return entry

    async def grant(
        self,
        organization_id: uuid.UUID,
        credits: float,
        *,
        kind: CreditEntryKind = CreditEntryKind.GRANT,
        actor_user_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> CreditEntry:
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            raise ValueError("Organization not found")
        entry = await self._append(
            organization, kind=kind, amount=abs(credits), actor_user_id=actor_user_id, note=note
        )
        await self.db.commit()
        await self.db.refresh(entry)
        log.info(
            "billing.granted",
            organization_id=str(organization_id),
            credits=credits,
            balance=organization.credit_balance,
        )
        return entry

    async def deduct(
        self,
        organization_id: uuid.UUID,
        credits: float,
        *,
        actor_user_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> CreditEntry:
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            raise ValueError("Organization not found")
        entry = await self._append(
            organization,
            kind=CreditEntryKind.ADJUSTMENT,
            amount=-abs(credits),
            actor_user_id=actor_user_id,
            note=note,
        )
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    # --- reservations --------------------------------------------------

    async def reserve_for_call(
        self, organization_id: uuid.UUID, call_id: uuid.UUID, *, estimated_cost_usd: float
    ) -> CreditReservation | None:
        """Hold credits before the phone rings.

        Idempotent on call id, because an origination that is retried must not
        stack a second hold on the same call.
        """
        existing = (
            (
                await self.db.execute(
                    select(CreditReservation).where(CreditReservation.call_id == call_id)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return existing

        amount = max(MINIMUM_CALL_CREDITS, self.credits_for(estimated_cost_usd * RESERVE_MINUTES))
        reservation = CreditReservation(
            organization_id=organization_id,
            call_id=call_id,
            amount=amount,
            status=ReservationStatus.HELD,
            note=f"{RESERVE_MINUTES:.0f} min estimate",
        )
        self.db.add(reservation)
        await self.db.commit()
        await self.db.refresh(reservation)
        log.info(
            "billing.reserved",
            call_id=str(call_id),
            credits=amount,
            spendable=await self.spendable(organization_id),
        )
        return reservation

    async def release_reservation(
        self, call_id: uuid.UUID, *, status: ReservationStatus = ReservationStatus.RELEASED
    ) -> None:
        """Give held credits back without charging.

        Used when a call never connected, so there is nothing to bill.
        """
        reservation = (
            (
                await self.db.execute(
                    select(CreditReservation).where(
                        CreditReservation.call_id == call_id,
                        CreditReservation.status == ReservationStatus.HELD,
                    )
                )
            )
            .scalars()
            .first()
        )
        if reservation is None:
            return
        reservation.status = status
        reservation.settled_amount = 0.0
        reservation.released_at = datetime.now(UTC)
        await self.db.commit()
        log.info("billing.released", call_id=str(call_id), credits=reservation.amount)

    async def expire_stale_reservations(self) -> int:
        """Return credits held for calls that never reported a terminal state.

        A dropped webhook would otherwise freeze a customer's credits forever,
        which looks identical to having been charged for a call that never ran.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=RESERVATION_TTL_MINUTES)
        rows = await self.db.execute(
            select(CreditReservation).where(
                CreditReservation.status == ReservationStatus.HELD,
                CreditReservation.created_at < cutoff,
            )
        )
        stale = list(rows.scalars())
        for reservation in stale:
            reservation.status = ReservationStatus.EXPIRED
            reservation.settled_amount = 0.0
            reservation.released_at = datetime.now(UTC)
        if stale:
            await self.db.commit()
            log.warning("billing.reservations_expired", count=len(stale))
        return len(stale)

    async def charge_for_call(self, call: Call) -> CreditEntry | None:
        """Bill a finished call, once.

        Idempotent on call id: post-call processing can be re-run, and a
        customer charged twice for one call would be the worst kind of bug here.
        """
        existing = await self.db.scalar(
            select(CreditEntry.id).where(
                CreditEntry.call_id == call.id, CreditEntry.kind == CreditEntryKind.USAGE
            )
        )
        if existing is not None:
            return None
        if call.duration_seconds <= 0:
            return None  # never connected; the carrier does not bill us either

        organization = await self.db.get(Organization, call.organization_id)
        if organization is None:
            return None

        credits = self.credits_for(call.cost_usd or 0.0)

        # Settle the hold: the charge below is the real cost, so whatever was
        # held above it goes back automatically when the hold closes.
        reservation = (
            (
                await self.db.execute(
                    select(CreditReservation).where(
                        CreditReservation.call_id == call.id,
                        CreditReservation.status == ReservationStatus.HELD,
                    )
                )
            )
            .scalars()
            .first()
        )
        if reservation is not None:
            reservation.status = ReservationStatus.SETTLED
            reservation.settled_amount = credits
            reservation.released_at = datetime.now(UTC)

        entry = await self._append(
            organization,
            kind=CreditEntryKind.USAGE,
            amount=-credits,
            call_id=call.id,
            note=f"{call.duration_seconds}s to {call.to_number}",
            provider_cost_usd=call.cost_usd,
        )
        await self.db.commit()
        await self.db.refresh(entry)
        log.info(
            "billing.charged",
            call_id=str(call.id),
            credits=credits,
            balance=organization.credit_balance,
        )
        return entry

    async def reconcile(self, organization_id: uuid.UUID) -> tuple[float, float]:
        """Rebuild the cached balance from the ledger. Returns (was, now)."""
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            return 0.0, 0.0
        was = float(organization.credit_balance)
        now = round(await self.ledger_total(organization_id), 2)
        if abs(was - now) > 0.001:
            log.warning(
                "billing.balance_drifted",
                organization_id=str(organization_id),
                cached=was,
                ledger=now,
            )
            organization.credit_balance = now
            await self.db.commit()
        return was, now

    async def suspend(
        self, organization_id: uuid.UUID, *, reason: str, actor_user_id: uuid.UUID | None = None
    ) -> Organization | None:
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            return None
        organization.suspended_at = datetime.now(UTC)
        organization.suspended_reason = reason[:300]
        await self.db.commit()
        log.warning(
            "billing.suspended",
            organization_id=str(organization_id),
            reason=reason,
            actor=str(actor_user_id),
        )
        return organization

    async def unsuspend(self, organization_id: uuid.UUID) -> Organization | None:
        organization = await self.db.get(Organization, organization_id)
        if organization is None:
            return None
        organization.suspended_at = None
        organization.suspended_reason = None
        await self.db.commit()
        return organization
