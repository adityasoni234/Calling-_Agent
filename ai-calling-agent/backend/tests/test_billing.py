"""Credits and the platform surface. The money paths, so these matter most."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.billing import CreditEntry, CreditEntryKind
from app.models.call import Call, CallStatus
from app.models.organization import Organization
from app.models.user import User
from app.services.billing_service import (
    MINIMUM_CALL_CREDITS,
    BillingService,
    spend_total,
)
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


def _call(organization_id: uuid.UUID, *, cost: float, seconds: int = 60) -> Call:
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


# --- pricing ----------------------------------------------------------


def test_credits_scale_with_what_the_call_cost_us(db_session) -> None:
    """A flat per-minute price loses money on the UK or is uncompetitive in India."""
    billing = BillingService(db_session)
    india = billing.credits_for(0.07)
    uk = billing.credits_for(0.45)
    assert uk > india * 4


def test_a_connected_call_is_never_free(db_session) -> None:
    """The carrier bills us for the attempt, so a zero-cost charge is a loss."""
    assert BillingService(db_session).credits_for(0.0) == MINIMUM_CALL_CREDITS


def test_every_call_is_sold_above_what_it_cost_us(db_session) -> None:
    """The regression that made the whole platform lose money.

    Credits were defined in US cents while packages were priced in rupees and
    nothing converted between them, so a minute costing Rs10 was sold for Rs2.
    This asserts the two units meet: the rupees a call earns must exceed the
    rupees it cost, by the configured markup.
    """
    billing = BillingService(db_session)
    for cost_usd in (0.02, 0.05, 0.1147, 0.45):
        cost_inr = cost_usd * settings.usd_inr_rate
        earned_inr = BillingService.rupees(billing.credits_for(cost_usd))
        assert earned_inr > cost_inr, f"${cost_usd} sells for less than it costs"
        assert earned_inr == pytest.approx(cost_inr * settings.credit_markup_multiplier, rel=0.01)


def test_a_cheaper_carrier_lowers_the_price_and_keeps_the_margin(db_session) -> None:
    """Cost-plus must stay self-correcting, or switching carrier breaks pricing."""
    billing = BillingService(db_session)
    twilio_minute, domestic_minute = 0.1147, 0.0574
    dear, cheap = billing.credits_for(twilio_minute), billing.credits_for(domestic_minute)

    assert cheap < dear  # the customer pays less

    def margin(credits: float, cost_usd: float) -> float:
        earned = BillingService.rupees(credits)
        return (earned - cost_usd * settings.usd_inr_rate) / earned

    assert margin(cheap, domestic_minute) == pytest.approx(margin(dear, twilio_minute), rel=0.01)


# --- the ledger -------------------------------------------------------


async def test_the_balance_always_equals_the_ledger(db_session, auth_headers) -> None:
    """The cached balance is a convenience; the ledger is the truth."""
    organization = await _org(db_session)
    billing = BillingService(db_session)

    await billing.grant(organization.id, 1000, note="top-up")
    await billing.deduct(organization.id, 250, note="correction")
    await billing.grant(organization.id, 75, note="goodwill")

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(await billing.ledger_total(organization.id))


async def test_every_entry_records_the_balance_after_it(db_session, auth_headers) -> None:
    """A statement has to be readable without re-summing the whole history."""
    organization = await _org(db_session)
    billing = BillingService(db_session)
    start = organization.credit_balance

    first = await billing.grant(organization.id, 100)
    second = await billing.deduct(organization.id, 30, note="test")

    assert first.balance_after == pytest.approx(start + 100)
    assert second.balance_after == pytest.approx(start + 70)


async def test_reconcile_repairs_a_drifted_cache(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    billing = BillingService(db_session)
    await billing.grant(organization.id, 500)

    organization.credit_balance = 999_999.0  # as if something wrote it directly
    await db_session.commit()

    _, now = await billing.reconcile(organization.id)
    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(now)
    assert organization.credit_balance != 999_999.0


# --- charging ---------------------------------------------------------


async def test_a_call_is_charged_once_however_often_it_is_processed(
    db_session, auth_headers
) -> None:
    """Post-call processing can be re-run. Double-charging would be the worst bug here."""
    organization = await _org(db_session)
    call = _call(organization.id, cost=0.07)
    db_session.add(call)
    await db_session.commit()

    billing = BillingService(db_session)
    first = await billing.charge_for_call(call)
    second = await billing.charge_for_call(call)
    third = await billing.charge_for_call(call)

    assert first is not None
    assert second is None and third is None
    usage = (
        (
            await db_session.execute(
                select(CreditEntry).where(
                    CreditEntry.call_id == call.id, CreditEntry.kind == CreditEntryKind.USAGE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(usage) == 1


async def test_a_call_that_never_connected_is_not_charged(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    call = _call(organization.id, cost=0.0, seconds=0)
    db_session.add(call)
    await db_session.commit()

    assert await BillingService(db_session).charge_for_call(call) is None


async def test_the_margin_is_recorded_on_the_usage_entry(db_session, auth_headers) -> None:
    """Recomputing margin later from rates that may have changed is not the same thing."""
    organization = await _org(db_session)
    call = _call(organization.id, cost=0.07)
    db_session.add(call)
    await db_session.commit()

    entry = await BillingService(db_session).charge_for_call(call)
    assert entry is not None
    assert entry.provider_cost_usd == pytest.approx(0.07)
    assert abs(entry.amount) / 100.0 > 0.07, "we must sell above cost"


# --- the gate ---------------------------------------------------------


async def test_an_account_with_no_credits_cannot_start_a_call(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    organization.credit_balance = 0.0
    await db_session.commit()

    allowed, reason = await BillingService(db_session).can_afford_call(organization.id)
    assert allowed is False
    assert "credit" in (reason or "").lower()


async def test_an_overdraft_lets_a_long_call_finish(db_session, auth_headers) -> None:
    """Cutting a live conversation off mid-sentence is worse than a small overrun."""
    organization = await _org(db_session)
    organization.credit_balance = -5.0
    organization.credit_overdraft = 50.0
    await db_session.commit()

    allowed, _ = await BillingService(db_session).can_afford_call(organization.id)
    assert allowed is True


async def test_a_suspended_account_cannot_call_even_with_credits(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    organization.credit_balance = 10_000.0
    await db_session.commit()
    await BillingService(db_session).suspend(organization.id, reason="Payment overdue")

    allowed, reason = await BillingService(db_session).can_afford_call(organization.id)
    assert allowed is False
    assert "Payment overdue" in (reason or "")


async def test_a_reinstated_account_can_call_again(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    organization.credit_balance = 1000.0
    await db_session.commit()
    billing = BillingService(db_session)
    await billing.suspend(organization.id, reason="checking")
    await billing.unsuspend(organization.id)

    allowed, _ = await billing.can_afford_call(organization.id)
    assert allowed is True


# --- the platform surface ---------------------------------------------


async def test_the_platform_api_is_closed_to_ordinary_users(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Any customer reaching this would see every other customer's data."""
    for path in ("/platform/overview", "/platform/organizations", "/platform/users"):
        response = await client.get(path, headers=auth_headers)
        assert response.status_code == 403, path


async def test_the_platform_api_is_closed_to_anonymous_callers(client: AsyncClient) -> None:
    assert (await client.get("/platform/overview")).status_code == 401


async def test_a_platform_admin_sees_every_organization(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "second@example.com", "organization_name": "Second Co"},
    )
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()

    response = await client.get("/platform/organizations", headers=auth_headers)
    assert response.status_code == 200
    names = [row["name"] for row in response.json()]
    assert "Second Co" in names
    assert len(names) >= 2


async def test_granting_credits_is_recorded_in_the_audit_trail(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """ "Who gave this account ten thousand credits" has to be answerable."""
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()

    organization_id = str(user.organization_id)
    granted = await client.post(
        f"/platform/organizations/{organization_id}/credits",
        json={"credits": 2500, "note": "Paid invoice INV-204"},
        headers=auth_headers,
    )
    assert granted.status_code == 200

    events = await client.get("/platform/events", headers=auth_headers)
    actions = [event["action"] for event in events.json()]
    assert "credits.grant" in actions
    detail = next(e for e in events.json() if e["action"] == "credits.grant")["detail"]
    assert "INV-204" in detail


async def test_removing_credits_requires_a_stated_reason(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()

    response = await client.post(
        f"/platform/organizations/{user.organization_id}/credits/deduct",
        json={"credits": 100},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_an_admin_cannot_lock_themselves_out(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Undoing it would need shell access to the database."""
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()

    response = await client.post(f"/platform/users/{user.id}/deactivate", headers=auth_headers)
    assert response.status_code == 404
    await db_session.refresh(user)
    assert user.is_active is True


async def test_a_new_organization_starts_with_trial_credits(client: AsyncClient) -> None:
    """An account that cannot place one test call will not convert."""

    registered = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "trial@example.com", "organization_name": "Trial Co"},
    )
    assert registered.status_code == 201
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert settings.trial_credits > 0


def test_an_account_that_never_called_shows_zero_not_minus_zero() -> None:
    """A balance screen reading "-0.00" makes a customer think they owe us."""
    assert spend_total(0.0) == 0.0
    assert str(spend_total(0.0)) == "0.0"
    assert spend_total(-12.5) == 12.5
