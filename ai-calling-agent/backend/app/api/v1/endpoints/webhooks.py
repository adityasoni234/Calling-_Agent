"""Telephony webhooks: answer documents and call-status callbacks.

Unauthenticated by necessity -- the carrier calls these. They are guarded by an
unguessable call id in the path plus an optional shared secret, and they only
ever advance a call the platform itself created.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import DbSession
from app.core.config import settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models.call import Call
from app.services.call_service import CallService
from app.services.campaign_service import CampaignService
from app.services.registry import get_telephony
from app.tasks.queue import enqueue_post_call

router = APIRouter(prefix="/webhooks/telephony", tags=["webhooks"])
log = get_logger(__name__)


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

    base = settings.public_base_url.rstrip("/")
    websocket_url = base.replace("https://", "wss://").replace("http://", "ws://")
    body, content_type = get_telephony(provider).answer_document(
        websocket_url=f"{websocket_url}/api/v1/media/{call_id}"
    )
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

    event = get_telephony(provider).parse_webhook(payload)
    was_open = call.status not in {"completed", "failed", "no_answer", "busy", "canceled"}
    call = await CallService(db).apply_event(call, event)
    log.info("webhook.status", call_id=str(call_id), event=event.type.value, status=call.status)

    if was_open and str(call.status) in {"completed", "failed", "no_answer", "busy", "canceled"}:
        if call.campaign_id:
            await CampaignService(db).on_call_finished(call)
        await enqueue_post_call(call.id)

    return {"status": "ok"}


@router.post("/{provider}/transfer", summary="Transfer document for a warm handoff")
async def transfer(provider: str, request: Request, to: str = Query(...)) -> Response:
    _check_secret(request)
    body, content_type = (
        f"<?xml version='1.0' encoding='UTF-8'?><Response><Dial>{to}</Dial></Response>",
        "application/xml",
    )
    return Response(content=body, media_type=content_type)
