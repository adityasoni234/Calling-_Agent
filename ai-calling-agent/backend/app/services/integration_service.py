"""API keys and outbound webhooks: the plug-and-play surface for a CRM.

Nothing here is specific to any one CRM. A generic signed webhook plus a key
that works on the existing REST API is what an integration actually needs, and
it costs nothing to support the next CRM after the first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.integration import (
    ApiKey,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
    WebhookEvent,
)

log = get_logger(__name__)

KEY_PREFIX = "cak_"
#: Stop hammering an endpoint that has failed this many times in a row.
MAX_CONSECUTIVE_FAILURES = 10
DELIVERY_TIMEOUT_SECONDS = 10.0


def _hash_key(raw: str) -> str:
    """SHA-256 rather than bcrypt: these are 32 bytes of entropy, not a password.

    There is no dictionary to attack, and a key is checked on every API request,
    so a deliberately slow hash would be a self-inflicted rate limit.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def sign(secret: str, body: bytes, timestamp: str) -> str:
    """Signature the receiver recomputes to prove the request came from us.

    The timestamp is inside the signed content so a captured delivery cannot be
    replayed later against the same endpoint.
    """
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


class IntegrationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- API keys ------------------------------------------------------

    async def create_key(self, organization_id: uuid.UUID, name: str) -> tuple[ApiKey, str]:
        """Return the record and the plaintext key, which is never stored."""
        raw = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key = ApiKey(
            organization_id=organization_id,
            name=name.strip() or "Untitled key",
            prefix=raw[: len(KEY_PREFIX) + 6],
            hashed_key=_hash_key(raw),
        )
        self.db.add(key)
        await self.db.commit()
        await self.db.refresh(key)
        log.info("integration.key_created", organization_id=str(organization_id), name=key.name)
        return key, raw

    async def resolve_key(self, raw: str) -> ApiKey | None:
        """Find the live key matching this plaintext, or None."""
        if not raw or not raw.startswith(KEY_PREFIX):
            return None
        rows = await self.db.execute(
            select(ApiKey).where(
                ApiKey.prefix == raw[: len(KEY_PREFIX) + 6], ApiKey.revoked_at.is_(None)
            )
        )
        digest = _hash_key(raw)
        for candidate in rows.scalars():
            # compare_digest, not ==, so a timing difference cannot leak the hash.
            if hmac.compare_digest(candidate.hashed_key, digest):
                candidate.last_used_at = datetime.now(UTC)
                await self.db.commit()
                return candidate
        return None

    async def revoke_key(self, key: ApiKey) -> None:
        key.revoked_at = datetime.now(UTC)
        await self.db.commit()

    # --- webhooks ------------------------------------------------------

    async def create_endpoint(
        self,
        organization_id: uuid.UUID,
        *,
        url: str,
        events: list[str],
        description: str | None = None,
    ) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(
            organization_id=organization_id,
            url=url,
            secret=secrets.token_urlsafe(32),
            events=events or [event.value for event in WebhookEvent],
            description=description,
        )
        self.db.add(endpoint)
        await self.db.commit()
        await self.db.refresh(endpoint)
        return endpoint

    async def queue(
        self, organization_id: uuid.UUID, event: WebhookEvent, payload: dict[str, Any]
    ) -> int:
        """Record a delivery per subscribed endpoint. Sending happens in the worker.

        Writing the row first means an event survives a crash between "it
        happened" and "we told them".
        """
        rows = await self.db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.organization_id == organization_id,
                WebhookEndpoint.is_active.is_(True),
            )
        )
        queued = 0
        for endpoint in rows.scalars():
            if endpoint.events and event.value not in endpoint.events:
                continue
            self.db.add(
                WebhookDelivery(
                    endpoint_id=endpoint.id,
                    event=event,
                    payload={
                        "event": event.value,
                        "sent_at": datetime.now(UTC).isoformat(),
                        "data": payload,
                    },
                )
            )
            queued += 1
        if queued:
            await self.db.commit()
        return queued

    async def deliver_pending(self, limit: int = 50) -> int:
        """Send queued deliveries. Called on a schedule by the worker."""
        rows = await self.db.execute(
            select(WebhookDelivery, WebhookEndpoint)
            .join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id)
            .where(WebhookDelivery.status == WebhookDeliveryStatus.PENDING)
            .order_by(WebhookDelivery.created_at)
            .limit(limit)
        )
        pending = rows.all()
        if not pending:
            return 0

        sent = 0
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            for delivery, endpoint in pending:
                delivery.attempts += 1
                body = json.dumps(delivery.payload, separators=(",", ":")).encode()
                timestamp = str(int(datetime.now(UTC).timestamp()))
                try:
                    response = await client.post(
                        endpoint.url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Calling-Agent-Event": str(delivery.event),
                            "X-Calling-Agent-Timestamp": timestamp,
                            "X-Calling-Agent-Signature": sign(endpoint.secret, body, timestamp),
                            "User-Agent": "calling-agent-webhooks/1",
                        },
                    )
                    delivery.response_code = response.status_code
                    if 200 <= response.status_code < 300:
                        delivery.status = WebhookDeliveryStatus.DELIVERED
                        delivery.error = None
                        endpoint.failure_count = 0
                        sent += 1
                    else:
                        raise httpx.HTTPError(f"HTTP {response.status_code}")
                except Exception as exc:
                    delivery.error = str(exc)[:500]
                    # Three tries, then stop -- an endpoint that has rejected the
                    # same payload three times will not accept it on the fourth.
                    if delivery.attempts >= 3:
                        delivery.status = WebhookDeliveryStatus.FAILED
                    endpoint.failure_count += 1
                    endpoint.last_error = str(exc)[:500]
                    if endpoint.failure_count >= MAX_CONSECUTIVE_FAILURES:
                        endpoint.is_active = False
                        log.warning(
                            "integration.endpoint_disabled",
                            endpoint_id=str(endpoint.id),
                            url=endpoint.url,
                        )
                endpoint.last_delivery_at = datetime.now(UTC)

        await self.db.commit()
        return sent
