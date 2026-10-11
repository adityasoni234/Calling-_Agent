"""Meta lead ads: OAuth, asset discovery and lead ingestion.

Uses Meta's official Graph API and OAuth only. Nothing here scrapes a
dashboard or asks a customer to paste a long-lived token into a form --
both are against Meta's terms and both put a credential somewhere it can be
read.

The flow Meta actually requires:

1. Send the user to Facebook with the scopes we need and a signed `state`.
2. Exchange the returned code for a short-lived token, then immediately
   exchange that for a long-lived one -- the short one dies in an hour and
   a connection that breaks after lunch is worse than one that never
   worked.
3. Read the Businesses, Pages and Lead Forms the user actually granted.
   Meta can issue fewer scopes than were asked for, so what was granted is
   recorded rather than assumed.
4. Subscribe the selected Page to `leadgen`, and verify the subscription
   was accepted rather than assuming it.

Every webhook is signature-verified before it is read. An unverified lead
webhook is an open endpoint for writing rows into a customer's CRM.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt, encrypt, mask
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.lead import Lead, LeadStatus
from app.models.meta import (
    MetaAsset,
    MetaAssetKind,
    MetaConnection,
    MetaConnectionStatus,
    MetaLeadEvent,
)

log = get_logger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
OAUTH_DIALOG = "https://www.facebook.com/v21.0/dialog/oauth"

#: The minimum that lead ingestion needs. Asking for more than this gets an
#: app rejected at review, and each one has to be justified to Meta.
SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "leads_retrieval",
    "business_management",
    "ads_read",
)


class MetaNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(
            "Meta is not configured. A Meta app id and secret are needed "
            "before customers can connect their ad accounts.",
            code="meta_unconfigured",
        )


@dataclass
class TokenGrant:
    access_token: str
    expires_at: datetime | None
    scopes: list[str]
    meta_user_id: str
    meta_user_name: str | None


def configured() -> bool:
    return bool(settings.meta_app_id and settings.meta_app_secret)


def verify_signature(body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256 before reading the payload.

    Without this the webhook is an unauthenticated endpoint that writes
    leads into a customer's CRM. Compared with `compare_digest` so a
    mismatch cannot be found a byte at a time.
    """
    if not settings.meta_app_secret or not header:
        return False
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.meta_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


class MetaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- OAuth ---------------------------------------------------------

    @staticmethod
    def authorize_url(state: str, redirect_uri: str) -> str:
        if not configured():
            raise MetaNotConfigured()
        from urllib.parse import urlencode

        return f"{OAUTH_DIALOG}?" + urlencode(
            {
                "client_id": settings.meta_app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": ",".join(SCOPES),
                "response_type": "code",
            }
        )

    @staticmethod
    def new_state() -> str:
        """Random, and checked on the way back, so the callback cannot be forged."""
        return secrets.token_urlsafe(32)

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenGrant:
        """Code to long-lived token, in the two steps Meta requires."""
        if not configured():
            raise MetaNotConfigured()

        async with httpx.AsyncClient(timeout=30.0) as client:
            short = await client.get(
                f"{GRAPH}/oauth/access_token",
                params={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            if short.status_code >= 400:
                raise AppError(self._error(short), code="meta_oauth_failed")
            short_token = short.json().get("access_token", "")

            # A short-lived token expires in about an hour. Exchanging
            # immediately is the difference between a connection that
            # lasts two months and one that breaks after lunch.
            long = await client.get(
                f"{GRAPH}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "fb_exchange_token": short_token,
                },
            )
            if long.status_code >= 400:
                raise AppError(self._error(long), code="meta_oauth_failed")
            payload = long.json()
            token = payload.get("access_token", short_token)
            expires_in = payload.get("expires_in")

            me = await client.get(
                f"{GRAPH}/me", params={"access_token": token, "fields": "id,name"}
            )
            profile = me.json() if me.status_code < 400 else {}

            # What Meta actually granted, which can be less than was asked.
            perms = await client.get(f"{GRAPH}/me/permissions", params={"access_token": token})
            granted = [
                row["permission"]
                for row in (perms.json().get("data", []) if perms.status_code < 400 else [])
                if row.get("status") == "granted"
            ]

        return TokenGrant(
            access_token=token,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
            ),
            scopes=granted,
            meta_user_id=str(profile.get("id", "")),
            meta_user_name=profile.get("name"),
        )

    @staticmethod
    def _error(response: httpx.Response) -> str:
        try:
            return (response.json().get("error") or {}).get(
                "message", f"Meta returned HTTP {response.status_code}"
            )
        except ValueError:
            return f"Meta returned HTTP {response.status_code}"

    async def save_connection(
        self,
        *,
        organization_id: uuid.UUID,
        grant: TokenGrant,
        user_id: uuid.UUID | None,
    ) -> MetaConnection:
        found = await self.db.execute(
            select(MetaConnection).where(
                MetaConnection.organization_id == organization_id,
                MetaConnection.meta_user_id == grant.meta_user_id,
            )
        )
        connection = found.scalars().first()
        if connection is None:
            connection = MetaConnection(
                organization_id=organization_id,
                meta_user_id=grant.meta_user_id,
            )
            self.db.add(connection)

        connection.connected_by_user_id = user_id
        connection.meta_user_name = grant.meta_user_name
        connection.access_token = encrypt(grant.access_token)
        connection.token_hint = mask(grant.access_token)
        connection.token_expires_at = grant.expires_at
        connection.scopes = grant.scopes
        connection.status = MetaConnectionStatus.CONNECTED
        connection.status_detail = None

        missing = [s for s in ("leads_retrieval", "pages_show_list") if s not in grant.scopes]
        if missing:
            # Surfaced now rather than as silently absent leads later.
            connection.status = MetaConnectionStatus.DEGRADED
            connection.status_detail = (
                "Missing permissions: " + ", ".join(missing) + ". "
                "Reconnect and accept them, or leads will not arrive."
            )

        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    def token_for(self, connection: MetaConnection) -> str:
        """Plaintext, for one Graph call. The only place it is decrypted."""
        return decrypt(connection.access_token)

    # --- assets --------------------------------------------------------

    async def sync_assets(self, connection: MetaConnection) -> list[MetaAsset]:
        """Read the Pages and Lead Forms this token can see.

        Existing rows are updated rather than replaced, so a form the
        customer already selected stays selected across a resync.
        """
        token = self.token_for(connection)
        discovered: list[tuple[MetaAssetKind, str, str, str | None, dict, str | None]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            pages = await client.get(
                f"{GRAPH}/me/accounts",
                params={"access_token": token, "fields": "id,name,access_token"},
            )
            if pages.status_code >= 400:
                connection.status = (
                    MetaConnectionStatus.EXPIRED
                    if pages.status_code in (401, 190)
                    else MetaConnectionStatus.DEGRADED
                )
                connection.status_detail = self._error(pages)
                await self.db.commit()
                return []

            for page in pages.json().get("data", []):
                page_id = str(page["id"])
                discovered.append(
                    (
                        MetaAssetKind.PAGE,
                        page_id,
                        page.get("name", page_id),
                        None,
                        {"id": page_id},
                        page.get("access_token"),
                    )
                )
                # Lead forms need the page's own token, not the user's.
                forms = await client.get(
                    f"{GRAPH}/{page_id}/leadgen_forms",
                    params={
                        "access_token": page.get("access_token") or token,
                        "fields": "id,name,status",
                    },
                )
                if forms.status_code >= 400:
                    continue
                for form in forms.json().get("data", []):
                    discovered.append(
                        (
                            MetaAssetKind.LEAD_FORM,
                            str(form["id"]),
                            form.get("name", str(form["id"])),
                            page_id,
                            form,
                            None,
                        )
                    )

        existing = {
            row.meta_id: row
            for row in (
                await self.db.execute(
                    select(MetaAsset).where(MetaAsset.connection_id == connection.id)
                )
            ).scalars()
        }

        out: list[MetaAsset] = []
        for kind, meta_id, name, parent, raw, page_token in discovered:
            asset = existing.get(meta_id)
            if asset is None:
                asset = MetaAsset(
                    organization_id=connection.organization_id,
                    connection_id=connection.id,
                    kind=kind,
                    meta_id=meta_id,
                )
                self.db.add(asset)
            asset.name = name
            asset.parent_meta_id = parent
            asset.raw = raw
            if page_token:
                asset.page_token = encrypt(page_token)
            out.append(asset)

        connection.last_synced_at = datetime.now(UTC)
        await self.db.commit()
        return out

    async def subscribe_page(self, connection: MetaConnection, page: MetaAsset) -> bool:
        """Subscribe a Page to leadgen, and verify Meta accepted it.

        Assuming success here is how a customer discovers three weeks later
        that no leads ever arrived.
        """
        if page.page_token is None:
            return False
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GRAPH}/{page.meta_id}/subscribed_apps",
                params={
                    "access_token": decrypt(page.page_token),
                    "subscribed_fields": "leadgen",
                },
            )
        ok = response.status_code < 400 and response.json().get("success") is True
        page.is_subscribed = ok
        if not ok:
            log.warning("meta.subscribe_failed", page=page.meta_id)
        await self.db.commit()
        return ok

    # --- leads ---------------------------------------------------------

    async def record_event(self, entry: dict, change: dict) -> MetaLeadEvent | None:
        """Write the webhook down before processing it.

        Meta re-delivers, so the leadgen id is unique and a duplicate is
        recognised rather than becoming a second lead.
        """
        value = change.get("value") or {}
        leadgen_id = str(value.get("leadgen_id") or "")
        if not leadgen_id:
            return None

        found = await self.db.execute(
            select(MetaLeadEvent).where(MetaLeadEvent.leadgen_id == leadgen_id)
        )
        if (existing := found.scalars().first()) is not None:
            return existing

        page_id = str(value.get("page_id") or entry.get("id") or "")
        asset = (
            (await self.db.execute(select(MetaAsset).where(MetaAsset.meta_id == page_id)))
            .scalars()
            .first()
        )

        event = MetaLeadEvent(
            organization_id=asset.organization_id if asset else None,
            connection_id=asset.connection_id if asset else None,
            leadgen_id=leadgen_id,
            form_id=str(value.get("form_id") or "") or None,
            page_id=page_id or None,
            ad_id=str(value.get("ad_id") or "") or None,
            adset_id=str(value.get("adgroup_id") or "") or None,
            campaign_id=str(value.get("campaign_id") or "") or None,
            raw={"entry": entry, "change": change},
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def process_event(self, event: MetaLeadEvent) -> Lead | None:
        """Fetch the submitted fields and turn them into a Lead.

        Deduplicated against existing leads by phone or email, because the
        same person filling in two forms is one contact -- but the Meta
        attribution is kept either way.
        """
        if event.processed_at is not None or event.organization_id is None:
            return None

        connection = (
            await self.db.get(MetaConnection, event.connection_id) if event.connection_id else None
        )
        if connection is None or not connection.is_usable:
            event.error = "No usable Meta connection for this page"
            await self.db.commit()
            return None

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GRAPH}/{event.leadgen_id}",
                params={
                    "access_token": self.token_for(connection),
                    "fields": "field_data,created_time,ad_id,form_id,campaign_id",
                },
            )
        if response.status_code >= 400:
            event.error = self._error(response)
            await self.db.commit()
            return None

        payload = response.json()
        fields = {
            str(item.get("name", "")).lower(): (item.get("values") or [""])[0]
            for item in payload.get("field_data", [])
        }
        event.raw = {**event.raw, "field_data": payload.get("field_data")}

        phone = fields.get("phone_number") or fields.get("phone") or ""
        email = fields.get("email") or ""
        name = (
            fields.get("full_name")
            or " ".join(filter(None, [fields.get("first_name"), fields.get("last_name")]))
            or "Meta lead"
        )
        if not phone and not email:
            event.error = "The form returned neither a phone number nor an email"
            event.processed_at = datetime.now(UTC)
            await self.db.commit()
            return None

        lead = await self._upsert_lead(
            event.organization_id, name=name, phone=phone, email=email, event=event
        )
        event.lead_id = lead.id
        event.processed_at = datetime.now(UTC)
        connection.leads_received = (connection.leads_received or 0) + 1
        connection.last_lead_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def _upsert_lead(
        self,
        organization_id: uuid.UUID,
        *,
        name: str,
        phone: str,
        email: str,
        event: MetaLeadEvent,
    ) -> Lead:
        from app.services.messaging_service import SendBlocked, normalise_number

        normalised = ""
        if phone:
            try:
                normalised, _ = normalise_number(phone)
            except SendBlocked:
                normalised = phone

        existing = None
        if normalised:
            existing = (
                (
                    await self.db.execute(
                        select(Lead).where(
                            Lead.organization_id == organization_id,
                            Lead.phone_number == normalised,
                        )
                    )
                )
                .scalars()
                .first()
            )
        if existing is None and email:
            existing = (
                (
                    await self.db.execute(
                        select(Lead).where(
                            Lead.organization_id == organization_id,
                            Lead.email == email.lower(),
                        )
                    )
                )
                .scalars()
                .first()
            )

        source = f"meta:{event.form_id or event.page_id or 'lead_ad'}"
        if existing is not None:
            # Keep the original attribution; a repeat submission does not
            # overwrite which campaign first found this person.
            existing.name = existing.name or name
            existing.email = existing.email or (email.lower() or None)
            return existing

        lead = Lead(
            organization_id=organization_id,
            name=name,
            phone_number=normalised or phone,
            email=email.lower() or None,
            status=LeadStatus.NEW,
            source=source,
        )
        self.db.add(lead)
        await self.db.flush()
        return lead
