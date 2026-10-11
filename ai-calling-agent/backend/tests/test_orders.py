"""Packages, orders and credit allocation. The money paths.

Covers the directive's cases 1-5 and 10-13: correct credits, no double grant,
nothing on failure, amount mismatch rejected, server-decided pricing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import AppError, NotFoundError
from app.models.billing import CreditEntry, CreditEntryKind
from app.models.organization import Organization
from app.models.package import CreditPackage, OrderStatus
from app.models.user import User
from app.services.billing_service import BillingService
from app.services.order_service import OrderService
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _package(db_session, **overrides) -> CreditPackage:
    defaults = dict(
        name="Starter",
        slug=f"starter-{uuid.uuid4().hex[:8]}",
        price_minor=99900,  # ₹999.00
        currency="INR",
        tax_bps=1800,  # 18% GST
        base_credits=10_000,
        bonus_credits=1_000,
    )
    defaults.update(overrides)
    package = CreditPackage(**defaults)
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)
    return package


# --- pricing arithmetic -----------------------------------------------


async def test_totals_are_computed_in_integer_minor_units(db_session) -> None:
    """Float money is how a bill ends up a paisa out and nobody can explain it."""
    package = await _package(db_session)
    assert package.total_credits == 11_000
    assert package.tax_minor == 17_982  # 18% of ₹999.00, exactly
    assert package.payable_minor == 117_882  # ₹1,178.82
    assert isinstance(package.payable_minor, int)


async def test_a_tax_free_package_adds_nothing(db_session) -> None:
    package = await _package(db_session, tax_bps=0)
    assert package.tax_minor == 0
    assert package.payable_minor == package.price_minor


# --- order creation ---------------------------------------------------


async def test_an_order_snapshots_the_terms_it_was_bought_under(db_session, auth_headers) -> None:
    """Changing a price must never rewrite what a past customer paid."""
    organization = await _org(db_session)
    package = await _package(db_session)
    order = await OrderService(db_session).create_order(
        organization_id=organization.id, package_id=package.id
    )

    package.price_minor = 500_000
    package.base_credits = 1
    package.name = "Renamed"
    await db_session.commit()

    await db_session.refresh(order)
    assert order.price_minor == 99900
    assert order.total_credits == 11_000
    assert order.package_name == "Starter"


async def test_the_price_comes_from_the_database_not_the_caller(
    client, auth_headers, db_session
) -> None:
    """A client that can name its own price can buy 10,000 credits for ₹1."""
    organization = await _org(db_session)
    package = await _package(db_session)
    order = await OrderService(db_session).create_order(
        organization_id=organization.id, package_id=package.id
    )
    # Nothing in create_order accepts an amount; the only source is the package.
    assert order.total_minor == package.payable_minor


async def test_a_purchase_limit_is_enforced(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    package = await _package(db_session, max_per_organization=1)
    service = OrderService(db_session)

    first = await service.create_order(organization_id=organization.id, package_id=package.id)
    await service.mark_paid(
        first,
        provider="test",
        provider_payment_id="pay_1",
        amount_minor=first.total_minor,
        currency="INR",
    )

    with pytest.raises(AppError) as caught:
        await service.create_order(organization_id=organization.id, package_id=package.id)
    assert caught.value.code == "package_limit_reached"


async def test_an_inactive_package_cannot_be_bought(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    package = await _package(db_session, is_active=False)
    with pytest.raises(NotFoundError):
        await OrderService(db_session).create_order(
            organization_id=organization.id, package_id=package.id
        )


# --- allocation -------------------------------------------------------


async def test_a_paid_order_grants_exactly_the_configured_credits(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    before = organization.credit_balance
    package = await _package(db_session)
    service = OrderService(db_session)

    order = await service.create_order(organization_id=organization.id, package_id=package.id)
    await service.mark_paid(
        order,
        provider="test",
        provider_payment_id="pay_ok",
        amount_minor=order.total_minor,
        currency="INR",
    )

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(before + 11_000)
    assert order.status is OrderStatus.PAID
    assert order.credits_allocated_at is not None


async def test_a_repeated_confirmation_does_not_grant_twice(db_session, auth_headers) -> None:
    """Providers retry webhooks; users refresh the success page. Both arrive twice."""
    organization = await _org(db_session)
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)

    for _ in range(4):
        await service.mark_paid(
            order,
            provider="test",
            provider_payment_id="pay_dup",
            amount_minor=order.total_minor,
            currency="INR",
        )

    entries = (
        (
            await db_session.execute(
                select(CreditEntry).where(
                    CreditEntry.order_id == order.id, CreditEntry.kind == CreditEntryKind.PURCHASE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1, "four confirmations granted credits more than once"


async def test_a_wrong_amount_is_rejected_and_grants_nothing(db_session, auth_headers) -> None:
    """A tampered checkout must never become credits."""
    organization = await _org(db_session)
    before = organization.credit_balance
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)

    with pytest.raises(AppError) as caught:
        await service.mark_paid(
            order,
            provider="test",
            provider_payment_id="pay_low",
            amount_minor=100,
            currency="INR",
        )
    assert caught.value.code == "amount_mismatch"

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(before)
    assert order.status is OrderStatus.FAILED
    assert order.credits_allocated_at is None


async def test_a_wrong_currency_is_rejected(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)

    with pytest.raises(AppError) as caught:
        await service.mark_paid(
            order,
            provider="test",
            provider_payment_id="pay_usd",
            amount_minor=order.total_minor,
            currency="USD",
        )
    assert caught.value.code == "currency_mismatch"


async def test_a_failed_payment_grants_nothing(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    before = organization.credit_balance
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)

    await service.mark_failed(order, "Card declined")

    await db_session.refresh(organization)
    assert organization.credit_balance == pytest.approx(before)
    assert order.status is OrderStatus.FAILED
    assert order.credits_allocated_at is None


async def test_a_late_failure_cannot_undo_a_completed_purchase(db_session, auth_headers) -> None:
    """A stale 'failed' event arriving after success must not strip credits."""
    organization = await _org(db_session)
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)
    await service.mark_paid(
        order,
        provider="test",
        provider_payment_id="pay_ok",
        amount_minor=order.total_minor,
        currency="INR",
    )
    balance = (await db_session.get(Organization, organization.id)).credit_balance

    await service.mark_failed(order, "late failure event")

    await db_session.refresh(organization)
    assert order.status is OrderStatus.PAID
    assert organization.credit_balance == pytest.approx(balance)


async def test_the_payment_can_be_traced_to_the_credits_it_granted(
    db_session, auth_headers
) -> None:
    """ "I paid but got no credits" has to be answerable by following links."""
    organization = await _org(db_session)
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)
    await service.mark_paid(
        order,
        provider="test",
        provider_payment_id="pay_trace",
        amount_minor=order.total_minor,
        currency="INR",
    )

    entry = (
        (await db_session.execute(select(CreditEntry).where(CreditEntry.order_id == order.id)))
        .scalars()
        .one()
    )
    assert entry.amount == order.total_credits
    assert order.reference in (entry.note or "")
    assert await BillingService(db_session).ledger_total(organization.id) == pytest.approx(
        (await db_session.get(Organization, organization.id)).credit_balance
    )


async def test_an_unallocated_paid_order_is_reported(db_session, auth_headers) -> None:
    """This report should always be empty; anything in it is an incident."""
    organization = await _org(db_session)
    package = await _package(db_session)
    service = OrderService(db_session)
    order = await service.create_order(organization_id=organization.id, package_id=package.id)

    assert await service.unallocated_paid_orders() == []

    # Simulate the failure mode: marked paid, allocation never ran.
    order.status = OrderStatus.PAID
    await db_session.commit()

    stuck = await service.unallocated_paid_orders()
    assert [o.id for o in stuck] == [order.id]


async def test_a_refund_can_never_exceed_what_was_paid(db_session, auth_headers) -> None:
    organization = await _org(db_session)
    package = await _package(db_session)
    order = await OrderService(db_session).create_order(
        organization_id=organization.id, package_id=package.id
    )
    order.refunded_minor = order.total_minor
    assert order.refundable_minor == 0

    order.refunded_minor = order.total_minor + 50_000  # as if over-refunded
    assert order.refundable_minor == 0, "refundable must never go negative"


# --- the customer-facing API ------------------------------------------


async def test_a_customer_sees_only_active_public_packages(
    client, auth_headers, db_session
) -> None:
    await _package(db_session, name="Visible", slug="vis-1", display_order=1)
    await _package(db_session, name="Retired", slug="ret-1", is_active=False)
    await _package(db_session, name="Hidden", slug="hid-1", is_public=False)

    names = [
        p["name"] for p in (await client.get("/billing/packages", headers=auth_headers)).json()
    ]
    assert "Visible" in names
    assert "Retired" not in names
    assert "Hidden" not in names


async def test_the_package_list_shows_server_computed_totals(
    client, auth_headers, db_session
) -> None:
    await _package(db_session, name="Priced", slug="priced-1")
    row = next(
        p
        for p in (await client.get("/billing/packages", headers=auth_headers)).json()
        if p["name"] == "Priced"
    )
    assert row["total_credits"] == 11_000
    assert row["payable_minor"] == 117_882


async def test_checkout_says_plainly_that_payments_are_not_set_up(
    client, auth_headers, db_session
) -> None:
    """A fake checkout that cannot complete is worse than an honest refusal."""
    package = await _package(db_session, slug="unconfigured-1")
    response = await client.post(
        "/billing/orders", json={"package_id": str(package.id)}, headers=auth_headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider_configured"] is False
    assert body["checkout"] is None
    assert "not set up" in body["message"].lower()
    # The order still exists, so the attempt is recoverable.
    assert body["order"]["status"] == "created"


async def test_confirming_without_a_provider_is_refused(client, auth_headers, db_session) -> None:
    package = await _package(db_session, slug="noconfirm-1")
    created = await client.post(
        "/billing/orders", json={"package_id": str(package.id)}, headers=auth_headers
    )
    order_id = created.json()["order"]["id"]
    response = await client.post(
        f"/billing/orders/{order_id}/confirm", json={"payload": {}}, headers=auth_headers
    )
    assert response.status_code >= 400
    assert "provider" in response.json()["error"]["code"]


async def test_a_customer_cannot_read_another_organizations_order(
    client, auth_headers, db_session
) -> None:
    """Changing the id in the URL must not work."""
    package = await _package(db_session, slug="isolation-1")
    mine = await client.post(
        "/billing/orders", json={"package_id": str(package.id)}, headers=auth_headers
    )
    order_id = mine.json()["order"]["id"]

    other = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "nosy@example.com", "organization_name": "Nosy Co"},
    )
    theirs = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    assert (await client.get(f"/billing/orders/{order_id}", headers=theirs)).status_code == 404
    assert (
        await client.get(f"/billing/orders/{order_id}", headers=auth_headers)
    ).status_code == 200


async def test_the_balance_endpoint_separates_held_from_spendable(
    client, auth_headers, db_session
) -> None:
    organization = await _org(db_session)
    await BillingService(db_session).grant(organization.id, 1000)

    body = (await client.get("/billing/credits/balance", headers=auth_headers)).json()
    assert body["spendable"] == pytest.approx(body["balance"] - body["held"])
    assert body["lifetime_granted"] >= 1000


async def test_a_viewer_cannot_spend_money(client, auth_headers, db_session) -> None:
    """Buying credits is an owner's decision, not a read-only user's."""
    from app.models.user import UserRole

    package = await _package(db_session, slug="viewer-1")
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.role = UserRole.VIEWER
    await db_session.commit()

    response = await client.post(
        "/billing/orders", json={"package_id": str(package.id)}, headers=auth_headers
    )
    assert response.status_code == 403
