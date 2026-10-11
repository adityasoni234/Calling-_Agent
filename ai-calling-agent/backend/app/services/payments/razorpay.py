"""Razorpay.

Chosen for India: UPI, cards and netbanking in one integration, and settlement
in INR without a currency conversion on every transaction.

Nothing here trusts the browser. The checkout handback is verified against the
signing secret, the webhook signature is checked before the body is parsed, and
the amount is re-read from the provider rather than taken from the request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.payments.base import (
    PaymentNotConfigured,
    PaymentProvider,
    ProviderOrder,
    VerifiedPayment,
)

log = get_logger(__name__)

API = "https://api.razorpay.com/v1"

#: Razorpay's payment states mapped onto ours. Their "captured" is the only
#: one that means money has actually moved.
STATUS_MAP = {
    "created": "pending",
    "authorized": "authorized",
    "captured": "paid",
    "refunded": "refunded",
    "failed": "failed",
}


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    @property
    def configured(self) -> bool:
        return bool(settings.razorpay_key_id and settings.razorpay_key_secret)

    def _auth(self) -> tuple[str, str]:
        if not self.configured:
            raise PaymentNotConfigured(
                "Razorpay is not configured. Add RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET, then restart."
            )
        return settings.razorpay_key_id, settings.razorpay_key_secret

    async def create_order(
        self, *, amount_minor: int, currency: str, reference: str, notes: dict[str, str]
    ) -> ProviderOrder:
        key_id, key_secret = self._auth()
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{API}/orders",
                auth=(key_id, key_secret),
                json={
                    "amount": amount_minor,
                    "currency": currency.upper(),
                    "receipt": reference,
                    # Razorpay only captures automatically when told to; the
                    # alternative leaves money authorised but not taken.
                    "payment_capture": 1,
                    "notes": notes,
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Razorpay rejected the order: {response.text[:300]}")

        data = response.json()
        return ProviderOrder(
            provider_order_id=data["id"],
            amount_minor=int(data["amount"]),
            currency=data["currency"],
            checkout={
                # The key id is publishable; the secret never leaves the server.
                "key": key_id,
                "order_id": data["id"],
                "amount": int(data["amount"]),
                "currency": data["currency"],
                "name": settings.app_name,
                "description": notes.get("package", "Credits"),
            },
        )

    def verify_checkout(self, payload: dict[str, Any]) -> VerifiedPayment:
        """Check the signature Razorpay's checkout hands back.

        This proves the browser's response was produced by Razorpay. It does
        not prove the payment was captured -- `fetch_payment` does that, and
        the caller must still do it.
        """
        _, key_secret = self._auth()
        order_id = str(payload.get("razorpay_order_id", ""))
        payment_id = str(payload.get("razorpay_payment_id", ""))
        signature = str(payload.get("razorpay_signature", ""))

        expected = hmac.new(
            key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Checkout signature did not match")

        return VerifiedPayment(
            provider_payment_id=payment_id,
            provider_order_id=order_id,
            amount_minor=0,  # unknown from the handback; fetched separately
            currency="",
            status="signature_ok",
            raw=payload,
        )

    def verify_webhook(self, *, body: bytes, signature: str) -> dict[str, Any]:
        secret = settings.razorpay_webhook_secret
        if not secret:
            raise PaymentNotConfigured("RAZORPAY_WEBHOOK_SECRET is not set")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise ValueError("Webhook signature did not match")
        return json.loads(body)

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        """Ask Razorpay directly. This is the only authority on payment."""
        key_id, key_secret = self._auth()
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{API}/payments/{provider_payment_id}", auth=(key_id, key_secret)
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Razorpay lookup failed: {response.text[:300]}")

        data = response.json()
        return VerifiedPayment(
            provider_payment_id=data["id"],
            provider_order_id=str(data.get("order_id", "")),
            amount_minor=int(data.get("amount", 0)),
            currency=str(data.get("currency", "")),
            status=STATUS_MAP.get(str(data.get("status")), str(data.get("status"))),
            raw=data,
        )

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, notes: dict[str, str]
    ) -> dict[str, Any]:
        key_id, key_secret = self._auth()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{API}/payments/{provider_payment_id}/refund",
                auth=(key_id, key_secret),
                json={"amount": amount_minor, "notes": notes},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Razorpay refused the refund: {response.text[:300]}")
        # Accepted is not the same as completed; the caller reconciles later.
        return response.json()


class UnconfiguredProvider(PaymentProvider):
    """Stands in when no provider is set up.

    Every method refuses. There is deliberately no simulated success path: a
    fake purchase that grants real credits is worse than no purchase at all.
    """

    name = "none"

    @property
    def configured(self) -> bool:
        return False

    def _refuse(self) -> None:
        raise PaymentNotConfigured(
            "No payment provider is configured. Set RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET to accept payments."
        )

    async def create_order(self, **_: Any) -> ProviderOrder:
        self._refuse()
        raise AssertionError  # unreachable; satisfies the return type

    def verify_checkout(self, payload: dict[str, Any]) -> VerifiedPayment:
        self._refuse()
        raise AssertionError

    def verify_webhook(self, *, body: bytes, signature: str) -> dict[str, Any]:
        self._refuse()
        raise AssertionError

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        self._refuse()
        raise AssertionError


def get_payment_provider() -> PaymentProvider:
    """The configured provider, or one that honestly refuses."""
    if settings.payment_provider == "razorpay":
        provider = RazorpayProvider()
        if provider.configured:
            return provider
    return UnconfiguredProvider()
