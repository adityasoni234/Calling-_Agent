"""Twilio SMS and WhatsApp.

WhatsApp rides the same Messages endpoint with a `whatsapp:` prefix on both
numbers, which is why one adapter serves both channels rather than two that
would drift apart.

Nothing here decides policy. By the time `send` is called the message has
already passed opt-out, consent, template and pricing checks in
`MessagingService`; this only talks to the vendor.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.messaging import Channel, MessageStatus
from app.services.messaging.base import (
    Dispatched,
    InboundMessage,
    MessagingNotConfigured,
    MessagingProvider,
)

log = get_logger(__name__)

API_BASE = "https://api.twilio.com/2010-04-01/Accounts"

#: Twilio's vocabulary mapped to ours. `undelivered` is kept distinct from
#: `failed`: the carrier accepted and billed us for the first but not the
#: second, and collapsing them would quietly absorb a real cost.
_STATUS = {
    "queued": MessageStatus.QUEUED,
    "accepted": MessageStatus.QUEUED,
    "scheduled": MessageStatus.QUEUED,
    "sending": MessageStatus.SENDING,
    "sent": MessageStatus.SENT,
    "receiving": MessageStatus.SENT,
    "received": MessageStatus.DELIVERED,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.READ,
    "undelivered": MessageStatus.UNDELIVERED,
    "failed": MessageStatus.FAILED,
    "canceled": MessageStatus.FAILED,
}


def _wire(number: str, channel: Channel) -> str:
    """WhatsApp numbers carry a scheme prefix on the wire."""
    if channel is not Channel.WHATSAPP:
        return number
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def _plain(number: str) -> str:
    return number.removeprefix("whatsapp:")


class TwilioMessaging(MessagingProvider):
    name = "twilio"

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        #: Injected by `get_messaging_provider`, which resolves the admin-managed
        #: connection before falling back to the environment.
        self._credentials = credentials

    def _resolved(self) -> dict[str, str]:
        if self._credentials is not None:
            return self._credentials
        return {
            "account_sid": settings.twilio_account_sid,
            "auth_token": settings.twilio_auth_token,
        }

    @property
    def configured(self) -> bool:
        creds = self._resolved()
        return bool(creds.get("account_sid") and creds.get("auth_token"))

    def _auth(self) -> tuple[str, str]:
        if not self.configured:
            raise MessagingNotConfigured(
                "Twilio messaging has no credentials. Set them in provider "
                "settings; nothing will be sent until they are present."
            )
        creds = self._resolved()
        return creds["account_sid"], creds["auth_token"]

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
        sid, token = self._auth()
        form: dict[str, str | list[str]] = {
            "To": _wire(to_number, channel),
            "From": _wire(from_number, channel),
            "Body": body or "",
        }
        if media_urls:
            form["MediaUrl"] = media_urls
        if status_callback:
            # Without this the message stays "sent" forever and we never
            # learn what it cost or whether it arrived.
            form["StatusCallback"] = status_callback

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{API_BASE}/{sid}/Messages.json", auth=(sid, token), data=form
                )
        except httpx.HTTPError as exc:
            # A network failure is not a rejected message. Reported as failed
            # with the reason, never swallowed into a fake success.
            log.warning("twilio.message_transport_error", error=str(exc))
            return Dispatched(
                provider_message_id=None,
                status=MessageStatus.FAILED,
                error_code="transport_error",
                error_message=str(exc),
            )

        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            log.warning(
                "twilio.message_rejected",
                status=response.status_code,
                code=payload.get("code"),
            )
            return Dispatched(
                provider_message_id=None,
                status=MessageStatus.FAILED,
                error_code=str(payload.get("code") or response.status_code),
                error_message=payload.get("message") or "Twilio rejected the message",
                raw=payload,
            )

        return Dispatched(
            provider_message_id=payload.get("sid"),
            status=_STATUS.get(payload.get("status", ""), MessageStatus.QUEUED),
            raw=payload,
        )

    def parse_webhook(self, form: dict) -> InboundMessage | None:
        """Handle both an inbound message and a delivery receipt.

        Twilio posts to the same shape for both; a receipt carries
        `MessageStatus` and no `Body`, an inbound message the reverse.
        """
        sid = form.get("MessageSid") or form.get("SmsSid")
        if not sid:
            return None

        raw_from = form.get("From", "")
        channel = (
            Channel.WHATSAPP
            if raw_from.startswith("whatsapp:") or form.get("To", "").startswith("whatsapp:")
            else Channel.SMS
        )
        raw_status = (form.get("MessageStatus") or form.get("SmsStatus") or "").lower()

        price = form.get("Price")
        cost: Decimal | None = None
        if price not in (None, ""):
            try:
                # Twilio reports spend as a negative number.
                cost = abs(Decimal(str(price)))
            except (ArithmeticError, ValueError):
                cost = None

        return InboundMessage(
            provider_message_id=sid,
            from_number=_plain(raw_from),
            to_number=_plain(form.get("To", "")),
            channel=channel,
            body=form.get("Body", "") or "",
            status=_STATUS.get(raw_status) if raw_status else None,
            provider_status=raw_status or None,
            error_code=form.get("ErrorCode") or None,
            cost=cost,
            currency=form.get("PriceUnit") or None,
            media_urls=[
                form[key] for key in sorted(form) if key.startswith("MediaUrl") and form.get(key)
            ],
        )


class UnconfiguredMessaging(MessagingProvider):
    """Stands in when no provider is set up, and says so.

    Deliberately has no "pretend it worked" path: a simulated success here
    would put a delivered-looking message in front of a customer whose
    recipient never received anything.
    """

    name = "none"

    @property
    def configured(self) -> bool:
        return False

    async def send(self, **_: object) -> Dispatched:
        raise MessagingNotConfigured(
            "No messaging provider is configured. Add Twilio credentials in "
            "provider settings to start sending."
        )

    def parse_webhook(self, form: dict) -> InboundMessage | None:
        return None


async def get_messaging_provider_async() -> MessagingProvider:
    """Resolve credentials from the admin-managed connection first.

    The sync version below stays for callers that cannot await; it reads only
    the environment, so anything using it will not see a rotation made in the
    admin until it is converted.
    """
    if settings.messaging_provider == "mock":
        from app.services.messaging.mock import MockMessaging

        return MockMessaging()

    from app.services.credentials import resolve

    twilio = TwilioMessaging(await resolve("twilio"))
    return twilio if twilio.configured else UnconfiguredMessaging()


def get_messaging_provider() -> MessagingProvider:
    """The configured provider, or one that refuses honestly.

    Selection is explicit rather than "use Twilio if keys happen to exist":
    a developer with real credentials in their environment should not start
    sending real messages because a test fixture forgot to opt out.
    """
    if settings.messaging_provider == "mock":
        from app.services.messaging.mock import MockMessaging

        return MockMessaging()
    twilio = TwilioMessaging()
    return twilio if twilio.configured else UnconfiguredMessaging()
