"""Carrier-facing callback URLs.

Built in one place so a configured `TELEPHONY_WEBHOOK_SECRET` is always present
on the URLs we hand to a carrier. Setting the secret without appending it would
make every webhook 403 and strand calls in `ringing`.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from app.core.config import settings


def _base() -> str:
    return settings.public_base_url.rstrip("/")


def _with_secret(url: str) -> str:
    if not settings.telephony_webhook_secret:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({'secret': settings.telephony_webhook_secret})}"


def answer_url(provider: str, call_id: uuid.UUID | str) -> str:
    return _with_secret(f"{_base()}/api/v1/webhooks/telephony/{provider}/answer/{call_id}")


def status_url(provider: str, call_id: uuid.UUID | str) -> str:
    return _with_secret(f"{_base()}/api/v1/webhooks/telephony/{provider}/status/{call_id}")


def inbound_url(provider: str) -> str:
    return _with_secret(f"{_base()}/api/v1/webhooks/telephony/{provider}/inbound")


def media_url(call_id: uuid.UUID | str) -> str:
    """WebSocket URL for the media stream.

    No secret: the unguessable call id is the credential, and carriers vary in
    whether they preserve query strings on a websocket upgrade.
    """
    scheme = _base().replace("https://", "wss://").replace("http://", "ws://")
    return f"{scheme}/api/v1/media/{call_id}"
