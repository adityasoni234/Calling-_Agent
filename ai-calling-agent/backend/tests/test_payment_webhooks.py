"""Razorpay's webhook, which is the path that works when the browser does not.

The point of these tests is the set of refusals. A webhook endpoint that
allocates credits is a thing an attacker would very much like to call, and a
webhook endpoint that returns the wrong status code is a thing Razorpay will
redeliver until the end of time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.organization import Organization
from app.models.package import CreditPackage, Order, OrderStatus
from app.models.user import User
from app.services import credentials
from app.services.order_service import OrderService
from app.services.payments.base import VerifiedPayment
from tests.conftest import REGISTRATION

WEBHOOK_SECRET = "whsec-test-secret"
PROVIDER_ORDER_ID = "order_TestRzp123"
PAYMENT_ID = "pay_TestRzp456"

URL = "/webhooks/payments/razorpay"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured provider, so the endpoint is doing verification and not
    short-circuiting on an unconfigured one."""
    monkeypatch.setattr(settings, "payment_provider", "razorpay", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_key", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_test_secret", raising=False)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET, raising=False)
    # Cold start, so these settings are what the vault resolver falls back
    # to rather than a value another test happened to resolve first.
    credentials.invalidate()


def _event(kind: str, *, amount: int, order_id: str = PROVIDER_ORDER_ID) -> dict[str, Any]:
    return {
        "event": kind,
        "payload": {
            "payment": {
                "entity": {
                    "id": PAYMENT_ID,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }


def _signed(event: dict[str, Any], *, secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(event).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "X-Razorpay-Signature": signature,
        "Content-Type": "application/json",
    }


async def _order(db_session, *, price_minor: int = 99900) -> dict[str, Any]:
    """Returns primitives, not the instance.

    Every request through `client` commits on its own session and expires
    this one, so an ORM object held across a request raises MissingGreenlet
    the moment a lazy attribute is touched.
    """
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    organization = await db_session.get(Organization, user.organization_id)
    package = CreditPackage(
        name="Starter",
        slug=f"starter-{uuid.uuid4().hex[:8]}",
        price_minor=price_minor,
        currency="INR",
        tax_bps=0,
        base_credits=10_000,
        bonus_credits=1_000,
    )
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)

    order = await OrderService(db_session).create_order(
        organization_id=organization.id, package_id=package.id, user_id=user.id
    )
    order.provider_order_id = PROVIDER_ORDER_ID
    await db_session.commit()
    await db_session.refresh(order)
    return {
        "id": order.id,
        "total_minor": order.total_minor,
        "currency": order.currency,
        "credits_allocated_at": order.credits_allocated_at,
    }


def _paid(order: dict[str, Any]) -> VerifiedPayment:
    return VerifiedPayment(
        provider_payment_id=PAYMENT_ID,
        provider_order_id=PROVIDER_ORDER_ID,
        amount_minor=order["total_minor"],
        currency=order["currency"],
        status="paid",
        raw={},
    )


async def test_a_captured_payment_allocates_credits_without_a_browser(
    client: AsyncClient, db_session, registered: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason this endpoint exists: nobody came back from checkout."""
    order = await _order(db_session)
    assert order["credits_allocated_at"] is None
    verified = _paid(order)

    async def _fetch(self, payment_id: str) -> VerifiedPayment:  # noqa: ANN001
        assert payment_id == PAYMENT_ID
        return verified

    monkeypatch.setattr("app.services.payments.razorpay.RazorpayProvider.fetch_payment", _fetch)

    body, headers = _signed(_event("payment.captured", amount=order["total_minor"]))
    response = await client.post(URL, content=body, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "allocated"

    db_session.expire_all()
    refreshed = await db_session.get(Order, order["id"])
    assert refreshed.status is OrderStatus.PAID
    assert refreshed.credits_allocated_at is not None


async def test_a_forged_signature_is_refused_and_not_acknowledged(
    client: AsyncClient, db_session, registered: dict
) -> None:
    """400, not 200.

    A 200 would tell Razorpay we accepted it and tell whoever sent it that
    their forgery went through quietly.
    """
    order = await _order(db_session)
    body, headers = _signed(
        _event("payment.captured", amount=order["total_minor"]), secret="not-the-secret"
    )

    response = await client.post(URL, content=body, headers=headers)
    assert response.status_code == 400

    db_session.expire_all()
    refreshed = await db_session.get(Order, order["id"])
    assert refreshed.credits_allocated_at is None


async def test_a_missing_signature_header_is_refused(
    client: AsyncClient, db_session, registered: dict
) -> None:
    order = await _order(db_session)
    body = json.dumps(_event("payment.captured", amount=order["total_minor"])).encode()

    response = await client.post(URL, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400

    db_session.expire_all()
    assert (await db_session.get(Order, order["id"])).credits_allocated_at is None


async def test_a_replayed_webhook_does_not_grant_twice(
    client: AsyncClient, db_session, registered: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Razorpay retries until acknowledged, so redelivery is normal, not an
    attack -- and it must not double the customer's credits."""
    order = await _order(db_session)
    verified = _paid(order)

    async def _fetch(self, payment_id: str) -> VerifiedPayment:  # noqa: ANN001
        return verified

    monkeypatch.setattr("app.services.payments.razorpay.RazorpayProvider.fetch_payment", _fetch)

    body, headers = _signed(_event("payment.captured", amount=order["total_minor"]))
    first = await client.post(URL, content=body, headers=headers)
    second = await client.post(URL, content=body, headers=headers)

    assert first.json()["status"] == "allocated"
    assert second.status_code == 200
    assert second.json()["status"] == "already allocated"

    db_session.expire_all()
    organization_id = (await db_session.get(Order, order["id"])).organization_id
    from app.models.billing import CreditEntry, CreditEntryKind

    grants = (
        (
            await db_session.execute(
                select(CreditEntry).where(
                    CreditEntry.organization_id == organization_id,
                    CreditEntry.kind == CreditEntryKind.PURCHASE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(grants) == 1


async def test_an_amount_that_does_not_match_the_order_is_rejected(
    client: AsyncClient, db_session, registered: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paying ₹1 for a ₹999 package must not buy ₹999 of credits."""
    order = await _order(db_session)
    underpaid = VerifiedPayment(
        provider_payment_id=PAYMENT_ID,
        provider_order_id=PROVIDER_ORDER_ID,
        amount_minor=100,
        currency="INR",
        status="paid",
        raw={},
    )

    async def _fetch(self, payment_id: str) -> VerifiedPayment:  # noqa: ANN001
        return underpaid

    monkeypatch.setattr("app.services.payments.razorpay.RazorpayProvider.fetch_payment", _fetch)

    body, headers = _signed(_event("payment.captured", amount=100))
    response = await client.post(URL, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    db_session.expire_all()
    refreshed = await db_session.get(Order, order["id"])
    assert refreshed.credits_allocated_at is None
    assert refreshed.status is OrderStatus.FAILED


async def test_the_provider_api_is_consulted_not_just_the_signed_body(
    client: AsyncClient, db_session, registered: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leaked webhook secret alone must not be able to mint credits.

    The event says captured; Razorpay's API says otherwise, and the API wins.
    """
    order = await _order(db_session)
    not_captured = VerifiedPayment(
        provider_payment_id=PAYMENT_ID,
        provider_order_id=PROVIDER_ORDER_ID,
        amount_minor=order["total_minor"],
        currency="INR",
        status="authorized",
        raw={},
    )

    async def _fetch(self, payment_id: str) -> VerifiedPayment:  # noqa: ANN001
        return not_captured

    monkeypatch.setattr("app.services.payments.razorpay.RazorpayProvider.fetch_payment", _fetch)

    body, headers = _signed(_event("payment.captured", amount=order["total_minor"]))
    response = await client.post(URL, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["reason"] == "authorized"

    db_session.expire_all()
    assert (await db_session.get(Order, order["id"])).credits_allocated_at is None


async def test_a_failed_payment_is_recorded_and_grants_nothing(
    client: AsyncClient, db_session, registered: dict
) -> None:
    order = await _order(db_session)
    event = _event("payment.failed", amount=order["total_minor"])
    event["payload"]["payment"]["entity"]["error_description"] = "Card declined by issuer"
    body, headers = _signed(event)

    response = await client.post(URL, content=body, headers=headers)
    assert response.status_code == 200

    db_session.expire_all()
    refreshed = await db_session.get(Order, order["id"])
    assert refreshed.status is OrderStatus.FAILED
    assert "declined" in (refreshed.failure_reason or "")
    assert refreshed.credits_allocated_at is None


async def test_an_event_we_do_not_act_on_is_acknowledged(client: AsyncClient) -> None:
    """200, so Razorpay stops. A non-2xx would have it redeliver every
    subscription and settlement event forever."""
    body, headers = _signed({"event": "settlement.processed", "payload": {}})
    response = await client.post(URL, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_an_unknown_order_is_acknowledged_rather_than_retried(
    client: AsyncClient,
) -> None:
    """Retrying cannot conjure an order. This happens when a test and a live
    environment share one Razorpay account, and it must not loop."""
    body, headers = _signed(
        _event("payment.captured", amount=1000, order_id="order_NeverSeenBefore")
    )
    response = await client.post(URL, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["reason"] == "unknown order"
