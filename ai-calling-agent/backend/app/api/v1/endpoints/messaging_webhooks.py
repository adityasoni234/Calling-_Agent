"""Twilio messaging callbacks: delivery receipts and inbound messages.

Unauthenticated because the carrier calls them. Two things make that safe
enough: a receipt can only advance a message the platform itself created and
whose provider id it already knows, and an inbound message is matched to a
tenant by the number they rent from us. An unrecognised id or number is
logged and ignored rather than creating anything.

Both handlers always return 200. Twilio retries a non-2xx, and retrying a
callback we have already applied just burns their quota and our logs -- the
handlers are idempotent, so there is nothing a retry would fix.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.core.logging import get_logger
from app.models.messaging import SuppressionReason
from app.services.messaging.twilio import get_messaging_provider
from app.services.messaging_service import MessagingService

router = APIRouter(prefix="/webhooks/messaging", tags=["webhooks"])
log = get_logger(__name__)

#: What a recipient types to stop. Twilio intercepts these on its own numbers,
#: but we record the opt-out too: the suppression list has to be ours, or it
#: disappears the day the carrier changes.
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke"}
START_WORDS = {"start", "unstop", "yes", "subscribe"}


async def _form(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return dict(await request.json())
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


@router.post("/status", summary="Delivery receipt")
async def delivery_receipt(request: Request, db: DbSession) -> dict:
    """Advance a message's status and record what the carrier charged."""
    payload = await _form(request)
    parsed = get_messaging_provider().parse_webhook(payload)
    if parsed is None or parsed.status is None:
        log.info("messaging.webhook_unparsed", keys=sorted(payload)[:8])
        return {"ok": True}

    message = await MessagingService(db).apply_status_update(
        provider_message_id=parsed.provider_message_id,
        status=parsed.status,
        provider_status=parsed.provider_status,
        provider_cost=parsed.cost,
        provider_currency=parsed.currency,
        error_code=parsed.error_code,
    )
    if message is None:
        # A receipt for something we never sent. Normal when credentials are
        # shared with another environment; not an error.
        log.info("messaging.receipt_unknown", sid=parsed.provider_message_id)
    return {"ok": True}


@router.post("/inbound", summary="Someone replied to us")
async def inbound(request: Request, db: DbSession) -> dict:
    """Store a reply, and honour STOP without waiting for anyone to notice."""
    payload = await _form(request)
    provider = get_messaging_provider()
    parsed = provider.parse_webhook(payload)
    if parsed is None:
        return {"ok": True}

    service = MessagingService(db)
    organization_id = await _tenant_for(db, parsed.to_number)
    if organization_id is None:
        log.warning("messaging.inbound_unknown_number", to=parsed.to_number)
        return {"ok": True}

    message = await service.record_inbound(
        organization_id=organization_id,
        channel=parsed.channel,
        from_number=parsed.from_number,
        to_number=parsed.to_number,
        body=parsed.body,
        provider=provider.name,
        provider_message_id=parsed.provider_message_id,
    )

    word = (parsed.body or "").strip().lower()
    if word in STOP_WORDS:
        await service.opt_out(
            organization_id,
            parsed.from_number,
            reason=SuppressionReason.OPT_OUT,
            channel=parsed.channel,
            source_message_id=message.id,
            note=f"Replied {word!r}",
        )
        log.info("messaging.opted_out", organization_id=str(organization_id))
    elif word in START_WORDS:
        # Un-suppressing is left to a human on purpose: "yes" in the middle of
        # a conversation is not an instruction to resume marketing.
        log.info("messaging.start_word_received", organization_id=str(organization_id))

    return {"ok": True}


async def _tenant_for(db: DbSession, to_number: str):
    """Which organization owns the number this message arrived on.

    Matched against the conversation history for that number first, then the
    platform's configured sender. Returning None rather than guessing keeps a
    stray message out of the wrong tenant's inbox, which is the one mistake
    here that would be a privacy incident.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from app.core.config import settings
    from app.models.messaging import Message
    from app.models.organization import Organization

    rows = await db.execute(
        select(Message.organization_id)
        .where(Message.from_number == to_number)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    found: _uuid.UUID | None = rows.scalars().first()
    if found is not None:
        return found

    if settings.twilio_caller_id and to_number.endswith(
        settings.twilio_caller_id.lstrip("+")[-10:]
    ):
        # Single-tenant fallback: the platform's own number belongs to the
        # only organization that has ever sent from it.
        first = await db.execute(select(Organization.id).order_by(Organization.created_at).limit(1))
        return first.scalars().first()
    return None
