"""An email provider that records instead of sending.

Lets the whole path -- validation, suppression, pricing, dispatch, events --
run end to end with no provider account and no risk of mailing a real
person during development.
"""

from __future__ import annotations

import uuid

from app.services.email.base import (
    EmailDispatched,
    EmailEvent,
    EmailProvider,
    OutboundEmail,
)


class MockEmail(EmailProvider):
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    @property
    def configured(self) -> bool:
        return True

    async def send(self, message: OutboundEmail) -> EmailDispatched:
        self.sent.append(message)
        return EmailDispatched(provider_message_id=f"mock-{uuid.uuid4().hex[:20]}", accepted=True)

    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        message_id = payload.get("MessageID") or payload.get("message_id")
        if not message_id:
            return None
        status = str(payload.get("status", "delivered"))
        return EmailEvent(
            provider_message_id=str(message_id),
            status=status,
            to_address=payload.get("to"),
            permanent=status == "bounced",
        )
