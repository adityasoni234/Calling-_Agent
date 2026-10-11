"""A messaging provider that records instead of sending.

Used by the test suite and by local development, so the whole path -- gates,
pricing, dispatch, receipts -- runs end to end without a carrier account or a
real phone bill.

It is honest about being a mock: `sent` holds everything it was handed, so a
test asserts on what would have gone out rather than on a stub returning
True.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.messaging import Channel, MessageStatus
from app.services.messaging.base import Dispatched, InboundMessage, MessagingProvider

#: Roughly a real Indian SMS, so local cost figures are not wildly wrong.
MOCK_COST = Decimal("0.0075")


class MockMessaging(MessagingProvider):
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    @property
    def configured(self) -> bool:
        return True

    async def send(
        self,
        *,
        to_number: str,
        from_number: str,
        body: str | None,
        channel: Channel,
        media_urls: list[str] | None = None,
        status_callback: str | None = None,
    ) -> Dispatched:
        record = {
            "to": to_number,
            "from": from_number,
            "body": body,
            "channel": str(channel),
            "media_urls": media_urls or [],
            "status_callback": status_callback,
        }
        self.sent.append(record)
        return Dispatched(
            provider_message_id=f"MOCK{uuid.uuid4().hex[:16]}",
            status=MessageStatus.SENT,
            raw=record,
        )

    def parse_webhook(self, form: dict) -> InboundMessage | None:
        sid = form.get("MessageSid")
        if not sid:
            return None
        raw_status = (form.get("MessageStatus") or "").lower()
        status = {
            "sent": MessageStatus.SENT,
            "delivered": MessageStatus.DELIVERED,
            "read": MessageStatus.READ,
            "undelivered": MessageStatus.UNDELIVERED,
            "failed": MessageStatus.FAILED,
        }.get(raw_status)
        return InboundMessage(
            provider_message_id=sid,
            from_number=form.get("From", ""),
            to_number=form.get("To", ""),
            channel=Channel.SMS,
            body=form.get("Body", "") or "",
            status=status,
            provider_status=raw_status or None,
            cost=MOCK_COST if status else None,
            currency="USD" if status else None,
        )
