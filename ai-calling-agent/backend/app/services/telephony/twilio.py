"""Twilio adapter.

Kept as the second implementation so the abstraction is proven against two real
backends rather than one, and as failover when a Plivo route degrades.
"""

from __future__ import annotations

import base64
from typing import Any
from xml.sax.saxutils import escape

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call import CallStatus
from app.services.base import ProviderError
from app.services.telephony.base import (
    OriginateResult,
    TelephonyEvent,
    TelephonyEventType,
    TelephonyProvider,
)

log = get_logger(__name__)
API_BASE = "https://api.twilio.com/2010-04-01/Accounts"

STATUS_MAP = {
    "queued": (TelephonyEventType.UNKNOWN, CallStatus.INITIATED),
    "initiated": (TelephonyEventType.UNKNOWN, CallStatus.INITIATED),
    "ringing": (TelephonyEventType.RINGING, CallStatus.RINGING),
    "in-progress": (TelephonyEventType.ANSWERED, CallStatus.IN_PROGRESS),
    "completed": (TelephonyEventType.COMPLETED, CallStatus.COMPLETED),
    "busy": (TelephonyEventType.COMPLETED, CallStatus.BUSY),
    "no-answer": (TelephonyEventType.COMPLETED, CallStatus.NO_ANSWER),
    "failed": (TelephonyEventType.FAILED, CallStatus.FAILED),
    "canceled": (TelephonyEventType.COMPLETED, CallStatus.CANCELED),
}


class TwilioTelephonyProvider(TelephonyProvider):
    name = "twilio"

    def _auth(self) -> tuple[str, str]:
        if not (settings.twilio_account_sid and settings.twilio_auth_token):
            raise ProviderError(self.name, "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set")
        return settings.twilio_account_sid, settings.twilio_auth_token

    async def originate(
        self, *, to_number: str, from_number: str, answer_url: str, status_url: str, call_id: str
    ) -> OriginateResult:
        sid, token = self._auth()
        form = {
            "To": to_number,
            "From": from_number or settings.twilio_caller_id,
            "Url": answer_url,
            "Method": "POST",
            "StatusCallback": status_url,
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{API_BASE}/{sid}/Calls.json", auth=(sid, token), data=form
                )
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")

        payload = response.json()
        log.info("telephony.originated", provider="twilio", provider_call_id=payload.get("sid"))
        return OriginateResult(provider_call_id=payload.get("sid", ""))

    async def hangup(self, provider_call_id: str) -> None:
        sid, token = self._auth()
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{API_BASE}/{sid}/Calls/{provider_call_id}.json",
                auth=(sid, token),
                data={"Status": "completed"},
            )

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        sid, token = self._auth()
        twiml = f"<Response><Dial>{escape(to_number)}</Dial></Response>"
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{API_BASE}/{sid}/Calls/{provider_call_id}.json",
                auth=(sid, token),
                data={"Twiml": twiml},
            )

    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Connect>"
            f'<Stream url="{escape(websocket_url)}" />'
            "</Connect></Response>"
        )
        return xml, "application/xml"

    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent:
        status = str(payload.get("CallStatus", "")).lower()
        event_type, call_status = STATUS_MAP.get(status, (TelephonyEventType.UNKNOWN, None))
        duration = payload.get("CallDuration")
        return TelephonyEvent(
            type=event_type,
            provider_call_id=str(payload.get("CallSid", "")),
            status=call_status,
            duration_seconds=int(duration) if duration else None,
            recording_url=payload.get("RecordingUrl"),
            raw=payload,
        )

    def decode_media(self, message: dict[str, Any]) -> bytes | None:
        if message.get("event") == "media":
            payload = message.get("media", {}).get("payload")
            if payload:
                return base64.b64decode(payload)
        return None

    def encode_media(self, audio: bytes, stream_id: str | None) -> dict[str, Any]:
        return {
            "event": "media",
            "streamSid": stream_id,
            "media": {"payload": base64.b64encode(audio).decode()},
        }

    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        return {"event": "clear", "streamSid": stream_id}

    def stream_id_from(self, message: dict[str, Any]) -> str | None:
        return message.get("streamSid") or message.get("start", {}).get("streamSid")
