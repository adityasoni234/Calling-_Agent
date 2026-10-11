"""Credit reservations: the fix for concurrent overspending.

Credits were charged only after a call finished, so the pre-call balance check
passed for every simultaneous call. These are the directive's tests 11, 13, 18.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.call import Call, CallStatus
from app.models.organization import Organization
from app.models.reservation import CreditReservation, ReservationStatus
from app.models.user import User
from app.services.billing_service import BillingService
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


def _call(organization_id: uuid.UUID, *, cost: float = 0.07, seconds: int = 60) -> Call:
    return Call(
        organization_id=organization_id,
        direction="outbound",
        provider="mock",
        from_number="+10000000000",
        to_number="+919876543210",
        status=CallStatus.COMPLETED,
        duration_seconds=seconds,
        cost_usd=cost,
    )


async def test_spendable_excludes_credits_held_by_live_calls(db_session, auth_headers) -> None:
    """Reading the raw balance is what let twenty calls each see the same credits."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)

    call = _call(organization.id)
    db_session.add(call)
    await db_session.commit()
    reservation = await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)

    await db_session.refresh(organization)
    assert reservation is not None
    assert await billing.held_credits(organization.id) == pytest.approx(reservation.amount)
    assert await billing.spendable(organization.id) == pytest.approx(
        organization.credit_balance - reservation.amount
    )


async def test_concurrent_calls_cannot_all_spend_the_same_credits(db_session, auth_headers) -> None:
    """The bug this whole table exists to fix."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    organization.credit_balance = 40.0
    organization.credit_overdraft = 0.0
    await db_session.commit()

    started = 0
    for _ in range(10):
        allowed, _ = await billing.can_afford_call(organization.id)
        if not allowed:
            break
        call = _call(organization.id)
        db_session.add(call)
        await db_session.commit()
        await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)
        started += 1

    assert started < 10, "an account with 40 credits must not start ten calls"
    assert await billing.spendable(organization.id) <= 0


async def test_a_reservation_is_not_stacked_when_origination_retries(
    db_session, auth_headers
) -> None:
    """Two holds on one call would silently double what cannot be spent."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)
    call = _call(organization.id)
    db_session.add(call)
    await db_session.commit()

    first = await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)
    second = await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)
    third = await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)

    assert first is not None
    assert second.id == first.id and third.id == first.id
    rows = (
        (
            await db_session.execute(
                select(CreditReservation).where(CreditReservation.call_id == call.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_settling_charges_the_real_cost_and_frees_the_rest(db_session, auth_headers) -> None:
    """The hold is an estimate; only actual usage may be charged."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)
    before = (await db_session.get(Organization, organization.id)).credit_balance

    call = _call(organization.id, cost=0.07, seconds=45)
    db_session.add(call)
    await db_session.commit()
    held = (
        await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)
    ).amount

    entry = await billing.charge_for_call(call)
    assert entry is not None

    reservation = (
        (
            await db_session.execute(
                select(CreditReservation).where(CreditReservation.call_id == call.id)
            )
        )
        .scalars()
        .one()
    )
    assert reservation.status is ReservationStatus.SETTLED
    assert reservation.settled_amount == pytest.approx(abs(entry.amount))
    assert reservation.settled_amount < held, "the estimate should exceed a 45-second call"

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(before - abs(entry.amount))
    assert await billing.held_credits(organization.id) == 0.0


async def test_a_call_that_never_connected_releases_everything(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)
    before = (await db_session.get(Organization, organization.id)).credit_balance

    call = _call(organization.id, seconds=0)
    db_session.add(call)
    await db_session.commit()
    await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)

    await billing.release_reservation(call.id)

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(before), "nothing was charged"
    assert await billing.held_credits(organization.id) == 0.0


async def test_a_hold_whose_call_never_reported_back_is_reclaimed(db_session, auth_headers) -> None:
    """A dropped webhook must not freeze a customer's credits forever."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)

    call = _call(organization.id)
    db_session.add(call)
    await db_session.commit()
    reservation = await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)
    reservation.created_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.commit()

    assert await billing.expire_stale_reservations() == 1
    await db_session.refresh(reservation)
    assert reservation.status is ReservationStatus.EXPIRED
    assert await billing.held_credits(organization.id) == 0.0


async def test_a_fresh_hold_is_not_reclaimed(db_session, auth_headers) -> None:
    """Reaping a live call's hold would let it overspend."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 1000)
    call = _call(organization.id)
    db_session.add(call)
    await db_session.commit()
    await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)

    assert await billing.expire_stale_reservations() == 0
    assert await billing.held_credits(organization.id) > 0


async def test_the_refusal_message_explains_held_credits(db_session, auth_headers) -> None:
    """ "Out of credits" is confusing when the balance looks positive."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    organization.credit_balance = 30.0
    organization.credit_overdraft = 0.0
    await db_session.commit()

    call = _call(organization.id)
    db_session.add(call)
    await db_session.commit()
    await billing.reserve_for_call(organization.id, call.id, estimated_cost_usd=0.05)

    allowed, reason = await billing.can_afford_call(organization.id)
    assert allowed is False
    assert "held for calls in progress" in (reason or "")
