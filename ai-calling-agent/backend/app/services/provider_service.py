"""Managing provider connections.

Credentials come in as plaintext exactly once, on the way to being encrypted,
and never go back out. Everything this service returns carries masked hints
instead -- the last four characters, which is what an operator compares
against a vendor dashboard, and which identify nothing on their own.

Rotation is a first-class operation rather than an update: who changed a key
and when is the question asked after an incident, so it is recorded rather
than inferred from a timestamp.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import SecretUnreadable, decrypt, encrypt, mask
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.provider import (
    ProviderConnection,
    ProviderKind,
    ProviderStatus,
)

log = get_logger(__name__)

#: Which secret fields each provider needs, and which are optional. Used to
#: validate a save and to drive the admin form, so the two cannot disagree.
PROVIDER_SPECS: dict[str, dict] = {
    "twilio": {
        "kind": ProviderKind.TELEPHONY,
        "label": "Twilio",
        "required": ["account_sid", "auth_token"],
        "optional": ["caller_id", "messaging_service_sid", "whatsapp_number"],
        "docs": "https://www.twilio.com/docs/usage/api",
    },
    "plivo": {
        "kind": ProviderKind.TELEPHONY,
        "label": "Plivo",
        "required": ["auth_id", "auth_token"],
        "optional": ["caller_id"],
        "docs": "https://www.plivo.com/docs/",
    },
    "anthropic": {
        "kind": ProviderKind.LLM,
        "label": "Anthropic",
        "required": ["api_key"],
        "optional": ["model"],
        "docs": "https://docs.claude.com/",
    },
    "deepgram": {
        "kind": ProviderKind.STT,
        "label": "Deepgram",
        "required": ["api_key"],
        "optional": ["model"],
        "docs": "https://developers.deepgram.com/",
    },
    "cartesia": {
        "kind": ProviderKind.TTS,
        "label": "Cartesia",
        "required": ["api_key"],
        "optional": ["voice_id"],
        "docs": "https://docs.cartesia.ai/",
    },
    "razorpay": {
        "kind": ProviderKind.PAYMENTS,
        "label": "Razorpay",
        "required": ["key_id", "key_secret"],
        "optional": ["webhook_secret"],
        "docs": "https://razorpay.com/docs/api/",
    },
}


@dataclass
class HealthResult:
    ok: bool
    detail: str
    checked_at: datetime


class ProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- reading -------------------------------------------------------

    async def list_connections(self) -> list[ProviderConnection]:
        rows = await self.db.execute(
            select(ProviderConnection).order_by(
                ProviderConnection.kind, ProviderConnection.priority
            )
        )
        return list(rows.scalars())

    async def get(self, connection_id: uuid.UUID) -> ProviderConnection:
        connection = await self.db.get(ProviderConnection, connection_id)
        if connection is None:
            raise NotFoundError("Provider connection not found")
        return connection

    async def by_slug(self, slug: str) -> ProviderConnection | None:
        rows = await self.db.execute(
            select(ProviderConnection).where(
                ProviderConnection.slug == slug,
                ProviderConnection.organization_id.is_(None),
            )
        )
        return rows.scalars().first()

    async def credentials(self, slug: str) -> dict[str, str]:
        """Decrypt a connection's secrets, for an adapter building a client.

        The only place plaintext leaves the database. Returns empty rather
        than raising when the provider is simply not configured, so callers
        can fall back; a secret that exists but cannot be decrypted does
        raise, because that is a broken deployment and not an absent one.
        """
        connection = await self.by_slug(slug)
        if connection is None or not connection.is_enabled:
            return {}
        try:
            return {key: decrypt(value) for key, value in (connection.secrets or {}).items()}
        except SecretUnreadable:
            log.error("provider.secret_unreadable", slug=slug)
            raise

    # --- writing -------------------------------------------------------

    async def upsert(
        self,
        *,
        slug: str,
        secrets: dict[str, str],
        config: dict | None = None,
        label: str | None = None,
        is_enabled: bool = True,
        environment: str = "live",
        actor_id: uuid.UUID | None = None,
    ) -> ProviderConnection:
        """Create or update a connection, encrypting every secret.

        A blank value means "leave this one alone" rather than "clear it", so
        an admin editing one key in a form does not wipe the others by
        submitting the masked placeholders back.
        """
        spec = PROVIDER_SPECS.get(slug)
        if spec is None:
            raise ValidationFailedError(f"{slug!r} is not a provider this platform integrates with")

        connection = await self.by_slug(slug)
        if connection is None:
            connection = ProviderConnection(
                slug=slug,
                label=label or spec["label"],
                kind=spec["kind"],
                environment=environment,
            )
            self.db.add(connection)

        stored = dict(connection.secrets or {})
        hints = dict(connection.secret_hints or {})
        rotated = False
        for key, value in secrets.items():
            if not value:
                continue  # untouched field
            stored[key] = encrypt(value)
            hints[key] = mask(value)
            rotated = True

        missing = [k for k in spec["required"] if k not in stored]
        if missing and is_enabled:
            raise ValidationFailedError(
                f"{spec['label']} needs {', '.join(missing)} before it can be enabled"
            )

        connection.secrets = stored
        connection.secret_hints = hints
        connection.config = {**(connection.config or {}), **(config or {})}
        connection.is_enabled = is_enabled
        connection.environment = environment
        if label:
            connection.label = label
        if rotated:
            connection.secrets_rotated_at = datetime.now(UTC)
            connection.secrets_rotated_by_id = actor_id
        connection.status = (
            ProviderStatus.UNCONFIGURED
            if not stored
            else ProviderStatus.DISABLED
            if not is_enabled
            # Unverified until a health check runs; claiming healthy on save
            # would show green for a key that was mistyped.
            else ProviderStatus.DEGRADED
        )
        connection.status_detail = None if stored else "No credentials saved"

        await self.db.commit()
        await self.db.refresh(connection)
        from app.services.credentials import invalidate

        invalidate(slug)
        log.info("provider.saved", slug=slug, rotated=rotated, enabled=is_enabled)
        return connection

    async def set_enabled(self, connection_id: uuid.UUID, enabled: bool) -> ProviderConnection:
        connection = await self.get(connection_id)
        connection.is_enabled = enabled
        connection.status = ProviderStatus.DEGRADED if enabled else ProviderStatus.DISABLED
        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    async def delete_secret(self, connection_id: uuid.UUID, key: str) -> ProviderConnection:
        """Remove one credential. Disables the connection if it was required."""
        connection = await self.get(connection_id)
        secrets = dict(connection.secrets or {})
        hints = dict(connection.secret_hints or {})
        secrets.pop(key, None)
        hints.pop(key, None)
        connection.secrets, connection.secret_hints = secrets, hints

        spec = PROVIDER_SPECS.get(connection.slug, {})
        if key in spec.get("required", []):
            connection.is_enabled = False
            connection.status = ProviderStatus.UNCONFIGURED
            connection.status_detail = f"{key} was removed"
        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    # --- health --------------------------------------------------------

    async def check(self, connection_id: uuid.UUID) -> HealthResult:
        """Ask the vendor whether these credentials work.

        A real request to the provider's own API, not a guess from whether
        the fields look populated. The result is written back so the admin
        list shows when it was last verified rather than implying "now".
        """
        connection = await self.get(connection_id)
        now = datetime.now(UTC)

        if not connection.secrets:
            result = HealthResult(False, "No credentials saved", now)
        else:
            try:
                secrets = {k: decrypt(v) for k, v in connection.secrets.items()}
                result = await self._probe(connection.slug, secrets, now)
            except SecretUnreadable as exc:
                result = HealthResult(False, str(exc), now)

        connection.last_checked_at = now
        connection.status = (
            ProviderStatus.HEALTHY
            if result.ok
            else ProviderStatus.DISABLED
            if not connection.is_enabled
            else ProviderStatus.DEGRADED
        )
        connection.status_detail = result.detail
        await self.db.commit()
        return result

    @staticmethod
    async def _probe(slug: str, secrets: dict, at: datetime) -> HealthResult:
        """One cheap authenticated read per vendor.

        Chosen to be free and side-effect-free: fetching an account record,
        never placing a call or sending a message.
        """
        probes: dict[str, tuple[str, dict]] = {
            "twilio": (
                f"https://api.twilio.com/2010-04-01/Accounts/{secrets.get('account_sid', '')}.json",
                {"auth": (secrets.get("account_sid", ""), secrets.get("auth_token", ""))},
            ),
            "anthropic": (
                "https://api.anthropic.com/v1/models",
                {
                    "headers": {
                        "x-api-key": secrets.get("api_key", ""),
                        "anthropic-version": "2023-06-01",
                    }
                },
            ),
            "deepgram": (
                "https://api.deepgram.com/v1/projects",
                {"headers": {"Authorization": f"Token {secrets.get('api_key', '')}"}},
            ),
            "cartesia": (
                "https://api.cartesia.ai/voices",
                {
                    "headers": {
                        "X-API-Key": secrets.get("api_key", ""),
                        "Cartesia-Version": "2024-06-10",
                    }
                },
            ),
        }
        probe = probes.get(slug)
        if probe is None:
            return HealthResult(False, f"No health check is implemented for {slug}", at)

        url, kwargs = probe
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            return HealthResult(False, f"Could not reach {slug}: {exc}", at)

        if response.status_code == 401:
            return HealthResult(False, "Credentials were rejected", at)
        if response.status_code == 402:
            # Valid keys, empty wallet. Distinguished because the fix is
            # entirely different and an operator should not go hunting for a
            # bad key when the account simply needs topping up.
            return HealthResult(False, "Authenticated, but the account is out of credit", at)
        if response.status_code >= 400:
            return HealthResult(False, f"{slug} returned HTTP {response.status_code}", at)
        return HealthResult(True, "Credentials verified", at)
