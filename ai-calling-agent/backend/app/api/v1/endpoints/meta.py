"""Meta lead ads: connect, select assets, receive leads.

The OAuth callback and the lead webhook are the two endpoints Meta itself
calls. Both are unauthenticated by necessity and both are guarded: the
callback by a one-time `state` we issued, the webhook by Meta's own
signature over the raw body.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, requires
from app.core.config import settings
from app.core.errors import AppError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.permissions import Capability
from app.models.meta import (
    MetaAsset,
    MetaAssetKind,
    MetaConnection,
    MetaConnectionStatus,
    MetaLeadEvent,
)
from app.models.user import User
from app.schemas.common import MessageResponse
from app.services.meta_service import (
    SCOPES,
    MetaService,
    configured,
    verify_signature,
)

router = APIRouter(prefix="/meta", tags=["meta"])
log = get_logger(__name__)

ManageUser = Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))]

#: Issued states, with the organization they belong to. In-process because a
#: state lives for the seconds between the redirect and the callback; a
#: multi-process deployment should move this to Redis.
_STATES: dict[str, tuple[uuid.UUID, uuid.UUID | None, float]] = {}
_STATE_TTL = 600.0


def _redirect_uri() -> str:
    return f"{settings.public_base_url}/api/v1/meta/callback"


def _prune() -> None:
    import time

    now = time.time()
    for key, (_, _, issued) in list(_STATES.items()):
        if now - issued > _STATE_TTL:
            _STATES.pop(key, None)


def _connection_read(connection: MetaConnection, assets: list[MetaAsset]) -> dict:
    """Never includes the token. Only its masked tail and expiry."""
    return {
        "id": str(connection.id),
        "meta_user_name": connection.meta_user_name,
        "status": str(connection.status),
        "status_detail": connection.status_detail,
        "token_hint": connection.token_hint,
        "token_expires_at": connection.token_expires_at.isoformat()
        if connection.token_expires_at
        else None,
        "is_usable": connection.is_usable,
        "scopes": connection.scopes,
        "last_synced_at": connection.last_synced_at.isoformat()
        if connection.last_synced_at
        else None,
        "last_lead_at": connection.last_lead_at.isoformat() if connection.last_lead_at else None,
        "leads_received": connection.leads_received,
        "assets": [
            {
                "id": str(a.id),
                "kind": str(a.kind),
                "meta_id": a.meta_id,
                "name": a.name,
                "parent_meta_id": a.parent_meta_id,
                "is_selected": a.is_selected,
                "is_subscribed": a.is_subscribed,
            }
            for a in assets
        ],
    }


# --- status and connect -----------------------------------------------


@router.get("/status", summary="Meta connection state")
async def meta_status(db: DbSession, user: CurrentUser) -> dict:
    """What is connected, and what is stopping it if nothing is."""
    rows = await db.execute(
        select(MetaConnection).where(MetaConnection.organization_id == user.organization_id)
    )
    connections = list(rows.scalars())

    out = []
    for connection in connections:
        assets = list(
            (
                await db.execute(
                    select(MetaAsset)
                    .where(MetaAsset.connection_id == connection.id)
                    .order_by(MetaAsset.kind, MetaAsset.name)
                )
            ).scalars()
        )
        out.append(_connection_read(connection, assets))

    blockers: list[str] = []
    if not configured():
        blockers.append(
            "Meta is not set up on this platform yet. A Meta app id and "
            "secret are needed before any customer can connect."
        )
    if not settings.public_base_url.startswith("https://"):
        blockers.append(
            "Meta requires an https callback URL. The current public URL is "
            "not https, so the connect flow will be rejected."
        )

    return {
        "platform_configured": configured(),
        "blockers": blockers,
        "connections": out,
        "required_scopes": list(SCOPES),
    }


@router.post("/connect", summary="Begin the Meta authorisation flow")
async def connect(db: DbSession, user: ManageUser) -> dict:
    """Return the URL to send the customer to.

    The state is random, single-use and tied to this organization, so a
    callback cannot be replayed or pointed at a different tenant.
    """
    _prune()
    import time

    state = MetaService.new_state()
    _STATES[state] = (user.organization_id, user.id, time.time())
    return {"authorize_url": MetaService.authorize_url(state, _redirect_uri())}


@router.get("/callback", summary="Where Meta sends the customer back")
async def callback(
    db: DbSession,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> Response:
    """Unauthenticated because Meta redirects the browser here.

    Safe because the state must be one we issued in the last ten minutes,
    and it names the organization. Consumed on use, so a replayed callback
    does nothing.
    """
    _prune()
    if error_description:
        return _result_page("Could not connect", error_description)
    if not code or not state or state not in _STATES:
        return _result_page(
            "Could not connect",
            "This link has expired or was already used. Start the connection again.",
        )

    organization_id, user_id, _ = _STATES.pop(state)
    service = MetaService(db)
    try:
        grant = await service.exchange_code(code, _redirect_uri())
        connection = await service.save_connection(
            organization_id=organization_id, grant=grant, user_id=user_id
        )
        await service.sync_assets(connection)
    except AppError as exc:
        return _result_page("Could not connect", str(exc))

    return _result_page(
        "Connected",
        "Your Meta account is linked. Close this window and choose which "
        "lead forms to pull leads from.",
    )


def _result_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{title}</title></head>
        <body style="font-family:system-ui,sans-serif;max-width:32rem;
        margin:4rem auto;padding:0 1.5rem;color:#2a2724;line-height:1.6">
        <h1 style="font-size:1.25rem">{title}</h1><p>{body}</p></body></html>"""
    )


# --- assets -----------------------------------------------------------


async def _connection(db: DbSession, user: User, connection_id: uuid.UUID) -> MetaConnection:
    connection = await db.get(MetaConnection, connection_id)
    if connection is None or connection.organization_id != user.organization_id:
        raise NotFoundError("Meta connection not found")
    return connection


@router.post("/connections/{connection_id}/sync", summary="Re-read pages and forms")
async def sync(connection_id: uuid.UUID, db: DbSession, user: ManageUser) -> dict:
    connection = await _connection(db, user, connection_id)
    assets = await MetaService(db).sync_assets(connection)
    await db.refresh(connection)
    return _connection_read(connection, assets)


@router.post("/assets/{asset_id}/select", summary="Pull leads from this form, or stop")
async def select_asset(
    asset_id: uuid.UUID, selected: bool, db: DbSession, user: ManageUser
) -> dict:
    """Selecting a lead form subscribes its Page to leadgen.

    Selecting a Page does not silently subscribe every form on it: a
    customer choosing one form has not agreed to ingest the others.
    """
    asset = await db.get(MetaAsset, asset_id)
    if asset is None or asset.organization_id != user.organization_id:
        raise NotFoundError("Asset not found")

    asset.is_selected = selected
    await db.commit()

    subscribed = None
    if selected and asset.kind is MetaAssetKind.LEAD_FORM and asset.parent_meta_id:
        page = (
            (
                await db.execute(
                    select(MetaAsset).where(
                        MetaAsset.connection_id == asset.connection_id,
                        MetaAsset.meta_id == asset.parent_meta_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if page is not None:
            connection = await db.get(MetaConnection, asset.connection_id)
            subscribed = await MetaService(db).subscribe_page(connection, page)

    return {
        "id": str(asset.id),
        "is_selected": asset.is_selected,
        "page_subscribed": subscribed,
    }


@router.delete("/connections/{connection_id}", summary="Disconnect")
async def disconnect(connection_id: uuid.UUID, db: DbSession, user: ManageUser) -> MessageResponse:
    """Delete the stored token and every asset derived from it.

    The token is destroyed rather than marked inactive: a credential kept
    after a customer asked to disconnect is a credential we should not have.
    """
    connection = await _connection(db, user, connection_id)
    connection.access_token = ""
    connection.token_hint = ""
    connection.status = MetaConnectionStatus.DISCONNECTED
    await db.delete(connection)
    await db.commit()
    return MessageResponse(message="Disconnected. The stored token has been deleted.")


@router.get("/leads", summary="Recent leads from Meta")
async def meta_leads(db: DbSession, user: CurrentUser, limit: int = 50) -> list[dict]:
    rows = await db.execute(
        select(MetaLeadEvent)
        .where(MetaLeadEvent.organization_id == user.organization_id)
        .order_by(MetaLeadEvent.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(e.id),
            "leadgen_id": e.leadgen_id,
            "form_id": e.form_id,
            "campaign_id": e.campaign_id,
            "lead_id": str(e.lead_id) if e.lead_id else None,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
            "error": e.error,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows.scalars()
    ]


# --- the webhook Meta calls -------------------------------------------


@router.get("/webhook", summary="Meta's subscription handshake")
async def verify_webhook(
    request: Request,
    db: DbSession,
) -> Response:
    """Echo the challenge back, but only for the token we configured.

    Meta calls this once when a webhook is registered. Echoing without
    checking would let anyone register our endpoint under their app.
    """
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token")
        and params.get("hub.verify_token") == settings.meta_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise PermissionDeniedError("Verification token mismatch", code="bad_verify_token")


@router.post("/webhook", summary="A lead was submitted")
async def lead_webhook(request: Request, db: DbSession) -> dict:
    """Signature-checked, then recorded, then processed.

    The raw body is read before parsing because the signature covers the
    exact bytes Meta sent; re-serialising the JSON would change them. An
    unverified lead webhook is an open endpoint for writing rows into a
    customer's CRM, so a bad signature is refused rather than logged.
    """
    body = await request.body()
    if not verify_signature(body, request.headers.get("x-hub-signature-256")):
        log.warning("meta.webhook_bad_signature")
        raise PermissionDeniedError("Invalid signature", code="bad_signature")

    payload = await request.json()
    service = MetaService(db)
    processed = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            event = await service.record_event(entry, change)
            if event is None or event.processed_at is not None:
                continue
            await service.process_event(event)
            processed += 1

    # Always 200. Meta retries a non-2xx, and the handler is idempotent on
    # the leadgen id, so a retry would find the event already recorded.
    return {"ok": True, "processed": processed}
