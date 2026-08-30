"""Telephony webhooks: answer documents and call-status callbacks.

Unauthenticated by necessity -- the carrier calls these. They are guarded by an
unguessable call id in the path plus an optional shared secret, and they only
ever advance a call the platform itself created.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import DbSession
from app.core.config import settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models.call import Call
from app.services.call_service import CallService
from app.services.campaign_service import CampaignService
from app.services.registry import get_telephony
from app.services.telephony import urls
from app.services.telephony.base import TelephonyEvent, TelephonyEventType
from app.tasks.queue import enqueue_post_call

router = APIRouter(prefix="/webhooks/telephony", tags=["webhooks"])
log = get_logger(__name__)


def _media_url(call_id: uuid.UUID) -> str:
    return urls.media_url(call_id)


async def _form_or_json(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return dict(await request.json())
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


def _check_secret(request: Request) -> None:
    if not settings.telephony_webhook_secret:
        return
    provided = request.query_params.get("secret") or request.headers.get("x-webhook-secret")
    if provided != settings.telephony_webhook_secret:
        raise PermissionDeniedError("Invalid webhook secret", code="bad_webhook_secret")


@router.post("/{provider}/answer/{call_id}", summary="Answer document for a live call")
async def answer(provider: str, call_id: uuid.UUID, request: Request, db: DbSession) -> Response:
    _check_secret(request)
    call = await db.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")

    body, content_type = get_telephony(provider).answer_document(websocket_url=_media_url(call_id))
    log.info("webhook.answer", call_id=str(call_id), provider=provider)
    return Response(content=body, media_type=content_type)


@router.post("/{provider}/status/{call_id}", summary="Call lifecycle callback")
async def status(
    provider: str, call_id: uuid.UUID, request: Request, db: DbSession
) -> dict[str, str]:
    _check_secret(request)
    payload = await _form_or_json(request)

    call = await db.get(Call, call_id)
    if call is None:
        log.warning("webhook.unknown_call", call_id=str(call_id))
        return {"status": "ignored"}

    adapter = get_telephony(provider)
    event = adapter.parse_webhook(payload)

    # Command-driven carriers (Telnyx) open the media stream from here, because
    # they have no answer document to carry it. No-op for Plivo and Twilio.
    try:
        await adapter.on_event(event, websocket_url=_media_url(call_id))
    except Exception as exc:
        log.error("webhook.on_event_failed", call_id=str(call_id), error=str(exc))

    was_open = call.status not in {"completed", "failed", "no_answer", "busy", "canceled"}
    call = await CallService(db).apply_event(call, event)
    log.info(
        "webhook.status",
        call_id=str(call_id),
        # Not `event=`: structlog reserves that for the log message itself,
        # and passing it raises TypeError inside the request handler.
        event_type=event.type.value,
        status=call.status,
    )

    if was_open and str(call.status) in {"completed", "failed", "no_answer", "busy", "canceled"}:
        if call.campaign_id:
            await CampaignService(db).on_call_finished(call)
        await enqueue_post_call(call.id)

    return {"status": "ok"}


@router.post("/{provider}/inbound", summary="Someone dialled our number")
async def inbound(provider: str, request: Request, db: DbSession) -> Response:
    """Application-level webhook: events for calls the platform did not place.

    Outbound calls report to their own per-call URL, so anything arriving here
    is an inbound leg. We create the call, answer it, and open the media stream
    -- the same conversation engine then runs unchanged.
    """
    _check_secret(request)
    payload = await _form_or_json(request)
    adapter = get_telephony(provider)

    if not adapter.is_inbound(payload):
        return JSONResponse({"status": "ignored"})

    provider_call_id, from_number, to_number = adapter.inbound_details(payload)
    service = CallService(db)
    if await service.by_provider_call_id(provider_call_id):
        return JSONResponse({"status": "duplicate"})

    call = await service.accept_inbound(
        provider=provider,
        provider_call_id=provider_call_id,
        from_number=from_number,
        to_number=to_number,
    )
    if call is None:
        return JSONResponse({"status": "no_agent"}, status_code=503)

    websocket_url = _media_url(call.id)
    log.info("webhook.inbound_answered", call_id=str(call.id), from_number=from_number)

    if adapter.answers_with_document:
        # Twilio and Plivo answer by acting on the document returned here.
        body, content_type = adapter.answer_document(websocket_url=websocket_url)
        return Response(content=body, media_type=content_type)

    # Call Control answers and opens the stream by command; acknowledge with JSON.
    await adapter.answer(provider_call_id)
    await adapter.on_event(
        TelephonyEvent(type=TelephonyEventType.ANSWERED, provider_call_id=provider_call_id),
        websocket_url=websocket_url,
    )
    return JSONResponse({"status": "answered", "call_id": str(call.id)})


@router.post("/{provider}/transfer", summary="Transfer document for a warm handoff")
async def transfer(provider: str, request: Request, to: str = Query(...)) -> Response:
    _check_secret(request)
    body, content_type = (
        f"<?xml version='1.0' encoding='UTF-8'?><Response><Dial>{to}</Dial></Response>",
        "application/xml",
    )
    return Response(content=body, media_type=content_type)
