"""Plivo adapter.

Default choice: India-registered entity, local DIDs, and bidirectional
WebSocket audio via `<Stream bidirectional="true">`, which is the requirement
barge-in imposes on any telephony vendor.
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
API_BASE = "https://api.plivo.com/v1/Account"


class PlivoTelephonyProvider(TelephonyProvider):
    name = "plivo"

    def _auth(self) -> tuple[str, str]:
        if not (settings.plivo_auth_id and settings.plivo_auth_token):
            raise ProviderError(self.name, "PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN are not set")
        return settings.plivo_auth_id, settings.plivo_auth_token

    async def originate(
        self,
        *,
        to_number: str,
        from_number: str,
        answer_url: str,
        status_url: str,
        call_id: str,
        record: bool = False,
    ) -> OriginateResult:
        auth = self._auth()
        body = {
            "to": to_number,
            "from": from_number or settings.plivo_caller_id,
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": status_url,
            "hangup_method": "POST",
            "ring_url": status_url,
            "ring_method": "POST",
            # Without this the carrier's own (often short) ring timeout applies.
            "ring_timeout": settings.ring_timeout_seconds,
        }
        if record:
            body["record"] = True
            body["record_file_format"] = "mp3"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(f"{API_BASE}/{auth[0]}/Call/", auth=auth, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")

        payload = response.json()
        provider_call_id = payload.get("request_uuid") or payload.get("call_uuid") or ""
        log.info("telephony.originated", provider="plivo", provider_call_id=provider_call_id)
        return OriginateResult(provider_call_id=provider_call_id)

    async def hangup(self, provider_call_id: str) -> None:
        auth = self._auth()
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.delete(f"{API_BASE}/{auth[0]}/Call/{provider_call_id}/", auth=auth)

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        auth = self._auth()
        transfer_url = (
            f"{settings.public_base_url}/api/v1/webhooks/telephony/plivo/transfer?to={to_number}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{API_BASE}/{auth[0]}/Call/{provider_call_id}/",
                auth=auth,
                json={"legs": "aleg", "aleg_url": transfer_url, "aleg_method": "POST"},
            )

    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        url = escape(websocket_url)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Stream bidirectional="true" keepCallAlive="true" '
            f'contentType="audio/x-mulaw;rate={self.sample_rate}">{url}</Stream>'
            "</Response>"
        )
        return xml, "application/xml"

    def is_inbound(self, payload: dict[str, Any]) -> bool:
        direction = str(payload.get("Direction", payload.get("CallDirection", ""))).lower()
        return direction in {"inbound", "incoming"} and bool(payload.get("CallUUID"))

    def inbound_details(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(payload.get("CallUUID", "")),
            str(payload.get("From", "")),
            str(payload.get("To", "")),
        )

    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent:
        status = str(payload.get("CallStatus") or payload.get("Status") or "").lower()
        hangup_cause = payload.get("HangupCause") or payload.get("HangupCauseName")

        if status == "ringing":
            event_type, call_status = TelephonyEventType.RINGING, CallStatus.RINGING
        elif status in {"in-progress", "answered"}:
            event_type, call_status = TelephonyEventType.ANSWERED, CallStatus.IN_PROGRESS
        elif status == "completed":
            event_type = TelephonyEventType.COMPLETED
            cause = (hangup_cause or "").upper()
            if "BUSY" in cause:
                call_status = CallStatus.BUSY
            elif "NO_ANSWER" in cause or "NOANSWER" in cause or "TIMEOUT" in cause:
                call_status = CallStatus.NO_ANSWER
            else:
                call_status = CallStatus.COMPLETED
        elif status in {"failed", "busy", "no-answer"}:
            event_type = TelephonyEventType.FAILED
            call_status = {
                "failed": CallStatus.FAILED,
                "busy": CallStatus.BUSY,
                "no-answer": CallStatus.NO_ANSWER,
            }[status]
        else:
            event_type, call_status = TelephonyEventType.UNKNOWN, None

        duration = payload.get("Duration") or payload.get("BillDuration")
        return TelephonyEvent(
            type=event_type,
            provider_call_id=str(payload.get("CallUUID") or payload.get("RequestUUID") or ""),
            status=call_status,
            duration_seconds=int(duration) if duration else None,
            recording_url=payload.get("RecordUrl"),
            hangup_cause=hangup_cause,
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
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": self.sample_rate,
                "payload": base64.b64encode(audio).decode(),
            },
        }

    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        # Flushes audio Plivo has buffered but not yet played -- without this,
        # cancelling TTS locally still leaves the agent talking for a second.
        return {"event": "clearAudio"}

    def stream_id_from(self, message: dict[str, Any]) -> str | None:
        return message.get("streamId") or message.get("start", {}).get("streamId")
