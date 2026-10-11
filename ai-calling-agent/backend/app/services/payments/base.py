"""Payment provider interface.

Shaped around what actually has to be trusted: the provider creates an order,
the browser pays it, and then *we* verify independently. A successful redirect
proves nothing -- anyone can navigate to a success URL -- so every provider must
offer a server-side check and a signed webhook, and both go through here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class PaymentNotConfigured(Exception):
    """Raised when a provider has no credentials.

    A distinct type so the API can answer "not set up yet" rather than a
    generic failure that looks like the payment was attempted and lost.
    """


@dataclass(slots=True)
class ProviderOrder:
    """What the browser needs to open a checkout."""

    provider_order_id: str
    amount_minor: int
    currency: str
    #: Safe to expose: the publishable key, the order id, display fields.
    checkout: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerifiedPayment:
    """The result of checking with the provider, not of trusting the client."""

    provider_payment_id: str
    provider_order_id: str
    amount_minor: int
    currency: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True only when real credentials are present.

        The UI uses this to say "not configured" plainly instead of offering a
        checkout that cannot work.
        """

    @abstractmethod
    async def create_order(
        self, *, amount_minor: int, currency: str, reference: str, notes: dict[str, str]
    ) -> ProviderOrder: ...

    @abstractmethod
    def verify_checkout(self, payload: dict[str, Any]) -> VerifiedPayment:
        """Verify what the browser handed back, using the signing secret."""

    @abstractmethod
    def verify_webhook(self, *, body: bytes, signature: str) -> dict[str, Any]:
        """Verify a webhook's signature. Raises if it does not match."""

    @abstractmethod
    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        """Ask the provider directly. The authority on whether money moved."""

    async def refund(
        self, *, provider_payment_id: str, amount_minor: int, notes: dict[str, str]
    ) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support refunds")
