"""The admin's 360 view of one customer.

Support calls start with "what happened on this account". Twenty numbers
assembled in one place is only useful if they agree with each other, so these
tests check the profile against the same facts read directly from the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.models.billing import CreditEntry, CreditEntryKind
from app.models.call import Call, CallSource, CallStatus
from app.models.organization import Organization
from app.models.package import CreditPackage, OrderStatus
from app.models.user import User
from app.core.config import settings
from app.services.order_service import OrderService
from tests.conftest import REGISTRATION


async def _admin(client: AsyncClient, db_session) -> User:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()
    return user


async def _package(db_session) -> CreditPackage:
    package = CreditPackage(
        name="Starter",
        slug=f"starter-{uuid.uuid4().hex[:8]}",
        price_minor=99900,
        currency="INR",
        tax_bps=1800,
        base_credits=10_000,
        bonus_credits=1_000,
    )
    db_session.add(package)
    await db_session.commit()
    return package


def _call(organization_id: uuid.UUID, *, source: CallSource, cost: float = 0.07) -> Call:
    return Call(
        organization_id=organization_id,
        direction="outbound",
        provider="mock",
        from_number="+10000000000",
        to_number="+919876543210",
        status=CallStatus.COMPLETED,
        source=source,
        duration_seconds=60,
        cost_usd=cost,
    )


async def test_the_profile_answers_the_whole_support_question(
    client: AsyncClient, auth_headers: dict[str, str], db_session, agent: dict
) -> None:
    user = await _admin(client, db_session)
    organization_id = user.organization_id

    db_session.add(_call(organization_id, source=CallSource.MANUAL))
    db_session.add(_call(organization_id, source=CallSource.CAMPAIGN))
    db_session.add(_call(organization_id, source=CallSource.CAMPAIGN))
    await db_session.commit()

    await client.post(
        f"/platform/organizations/{organization_id}/credits",
        json={"credits": 2500, "note": "Paid invoice INV-204"},
        headers=auth_headers,
    )

    response = await client.get(
        f"/platform/organizations/{organization_id}/profile", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()

    assert body["organization"]["name"] == REGISTRATION["organization_name"]
    assert [u["email"] for u in body["users"]] == [REGISTRATION["email"]]

    # Where the calls came from, which is the first thing asked about a bill.
    assert body["calls_total"] == 3
    assert body["by_source"] == {"manual": 1, "campaign": 2}
    assert body["minutes_30d"] == 3.0

    # The money.
    # The sign-up trial grant is part of the lifetime figure, not separate from it.
    assert body["lifetime_granted"] == 2500.0 + settings.trial_credits
    assert body["balance"] == body["organization"]["credit_balance"]
    assert body["spendable"] == body["balance"] - body["held"]

    # The agent the customer actually built, with its own usage attached.
    assert [a["name"] for a in body["agents"]] == [agent["name"]]

    assert len(body["recent_calls"]) == 3
    assert any(entry["kind"] == "grant" for entry in body["recent_credits"])
    assert body["unallocated_orders"] == []


async def test_the_profile_reports_paid_revenue_and_flags_stuck_orders(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """A paid order whose credits never landed is the one thing an admin must see."""
    user = await _admin(client, db_session)
    organization_id = user.organization_id
    package = await _package(db_session)

    orders = OrderService(db_session)
    paid = await orders.create_order(
        organization_id=organization_id, package_id=package.id, user_id=user.id
    )
    await orders.mark_paid(
        paid,
        provider="mock",
        provider_payment_id="pay_ok",
        amount_minor=paid.total_minor,
        currency=paid.currency,
    )

    stuck = await orders.create_order(
        organization_id=organization_id, package_id=package.id, user_id=user.id
    )
    stuck.status = OrderStatus.PAID
    stuck.credits_allocated_at = None
    await db_session.commit()

    body = (
        await client.get(f"/platform/organizations/{organization_id}/profile", headers=auth_headers)
    ).json()

    assert body["paid_orders"] == 2
    assert body["paid_minor"] == paid.total_minor * 2
    assert body["lifetime_purchased"] == 11_000.0  # only the one that allocated
    assert [o["id"] for o in body["unallocated_orders"]] == [str(stuck.id)]


async def test_an_unknown_organization_is_a_404_not_an_empty_profile(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    await _admin(client, db_session)
    response = await client.get(
        f"/platform/organizations/{uuid.uuid4()}/profile", headers=auth_headers
    )
    assert response.status_code == 404


async def test_a_customer_cannot_read_another_customers_profile(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The profile is the most revealing endpoint we have. It is admin-only."""
    organization = (await db_session.execute(select(Organization))).scalars().first()
    response = await client.get(
        f"/platform/organizations/{organization.id}/profile", headers=auth_headers
    )
    assert response.status_code == 403


async def test_margin_compares_the_same_window_on_both_sides(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Lifetime revenue against 30-day cost reports a loss on a profitable account."""
    user = await _admin(client, db_session)
    organization_id = user.organization_id
    old = datetime.now(UTC) - timedelta(days=90)

    db_session.add(
        CreditEntry(
            organization_id=organization_id,
            kind=CreditEntryKind.USAGE,
            amount=-400.0,
            balance_after=0.0,
            note="three months ago",
            created_at=old,
        )
    )
    db_session.add(
        CreditEntry(
            organization_id=organization_id,
            kind=CreditEntryKind.USAGE,
            amount=-100.0,
            balance_after=0.0,
            note="this month",
        )
    )
    await db_session.commit()

    body = (
        await client.get(f"/platform/organizations/{organization_id}/profile", headers=auth_headers)
    ).json()
    assert body["lifetime_consumed"] == 500.0
    assert body["consumed_30d"] == 100.0

    summary = next(
        row
        for row in (await client.get("/platform/organizations", headers=auth_headers)).json()
        if row["id"] == str(organization_id)
    )
    assert summary["credits_used"] == 500.0
    assert summary["credits_used_30d"] == 100.0
