"""Where an adapter gets its credentials.

Until now adapters read `settings` directly, so the Providers admin page
stored keys that nothing used -- an admin could rotate a Twilio token and
watch calls keep going out on the old one. This resolves the database first
and falls back to the environment.

Database first, not environment first, because the whole point of the admin
page is that it wins. The `.env` fallback stays so a fresh install works
before anyone has opened the admin, and so local development needs no setup.

Results are cached for a few seconds. A busy campaign resolves credentials
hundreds of times a minute and each one is a query plus a decrypt; a short
window keeps a rotation taking effect almost immediately while removing
nearly all of that work.
"""

from __future__ import annotations

import time

from app.core.config import settings
from app.core.crypto import SecretUnreadable
from app.core.logging import get_logger
from app.db.session import SessionLocal

log = get_logger(__name__)

#: Short enough that a rotation is live before an admin finishes reading the
#: confirmation, long enough to collapse a campaign's worth of lookups.
TTL_SECONDS = 15.0

#: How a stored connection's fields map onto the settings they override.
FALLBACKS: dict[str, dict[str, str]] = {
    "twilio": {
        "account_sid": "twilio_account_sid",
        "auth_token": "twilio_auth_token",
        "caller_id": "twilio_caller_id",
    },
    "plivo": {
        "auth_id": "plivo_auth_id",
        "auth_token": "plivo_auth_token",
        "caller_id": "plivo_caller_id",
    },
    "anthropic": {"api_key": "anthropic_api_key"},
    "deepgram": {"api_key": "deepgram_api_key"},
    "cartesia": {"api_key": "cartesia_api_key"},
    "google": {
        "client_id": "google_client_id",
        "client_secret": "google_client_secret",
    },
    "microsoft": {
        "client_id": "microsoft_client_id",
        "client_secret": "microsoft_client_secret",
    },
    "meta": {
        "app_id": "meta_app_id",
        "app_secret": "meta_app_secret",
        "verify_token": "meta_verify_token",
    },
    "razorpay": {
        "key_id": "razorpay_key_id",
        "key_secret": "razorpay_key_secret",
        "webhook_secret": "razorpay_webhook_secret",
    },
}

_cache: dict[str, tuple[float, dict[str, str]]] = {}


def _from_env(slug: str) -> dict[str, str]:
    return {
        field: value
        for field, attr in FALLBACKS.get(slug, {}).items()
        if (value := getattr(settings, attr, ""))
    }


async def resolve(slug: str) -> dict[str, str]:
    """Credentials for one provider: database if present, else environment."""
    cached = _cache.get(slug)
    if cached is not None and time.monotonic() - cached[0] < TTL_SECONDS:
        return cached[1]

    stored: dict[str, str] = {}
    try:
        async with SessionLocal() as db:
            from app.services.provider_service import ProviderService

            stored = await ProviderService(db).credentials(slug)
    except SecretUnreadable:
        # A key that cannot be decrypted is a broken deployment, not an
        # absent one. Falling back to .env here would hide it.
        raise
    except Exception as exc:  # noqa: BLE001 - never let config lookup break a call
        log.warning("credentials.lookup_failed", slug=slug, error=str(exc))

    resolved = {**_from_env(slug), **stored}
    _cache[slug] = (time.monotonic(), resolved)
    return resolved


def invalidate(slug: str | None = None) -> None:
    """Drop the cache after a rotation, so the new key is used immediately."""
    if slug is None:
        _cache.clear()
    else:
        _cache.pop(slug, None)


def get_sync(slug: str) -> dict[str, str]:
    """Credentials without awaiting, for adapters that are not async there.

    Reads the cache the async resolver fills. A cold cache falls back to the
    environment rather than blocking on a database round trip inside what may
    be an audio loop -- which is why `warm_all` runs at startup and every
    credential save re-resolves immediately. Without those two, a sync reader
    would keep using the environment until something else happened to warm
    the cache.
    """
    cached = _cache.get(slug)
    if cached is not None and time.monotonic() - cached[0] < TTL_SECONDS:
        return cached[1]
    return _from_env(slug)


async def warm_all() -> None:
    """Resolve every provider once, so sync readers start from the database."""
    for slug in FALLBACKS:
        try:
            await resolve(slug)
        except Exception as exc:  # noqa: BLE001 - startup must not fail on this
            log.warning("credentials.warm_failed", slug=slug, error=str(exc))
