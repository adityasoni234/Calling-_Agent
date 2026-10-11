"""The contract a messaging provider must satisfy.

Kept deliberately small. Everything policy-shaped -- opt-outs, consent,
segment counting, pricing, idempotency -- lives in `MessagingService` so it is
tested once and cannot drift between carriers. An adapter's only job is to
hand a message to a vendor and report, honestly, what the vendor said.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.messaging import Channel, MessageStatus


class MessagingNotConfigured(Exception):
    """The provider has no usable credentials.

    Raised rather than returning a fake success. A send that silently goes
    nowhere is worse than one that fails loudly, because the first is
    discovered by a customer and the second by us.
    """


@dataclass
class Dispatched:
    """What the provider said when we handed it the message."""

    provider_message_id: str | None
    status: MessageStatus
    error_code: str | None = None
    error_message: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.provider_message_id is not None and self.error_code is None


@dataclass
class InboundMessage:
    """A message or receipt parsed out of a provider webhook."""

    provider_message_id: str
    from_number: str
    to_number: str
    channel: Channel
    body: str = ""
    status: MessageStatus | None = None
    provider_status: str | None = None
    error_code: str | None = None
    cost: Decimal | None = None
    currency: str | None = None
    media_urls: list[str] = field(default_factory=list)


class MessagingProvider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def send(
        self,
        *,
        to_number: str,
        from_number: str,
        body: str | None,
        channel: Channel,
        media_urls: list[str] | None = None,
        status_callback: str | None = None,
    ) -> Dispatched: ...

    @abstractmethod
    def parse_webhook(self, form: dict) -> InboundMessage | None:
        """Turn a provider callback into our shape, or None if unrecognised."""
