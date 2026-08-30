"""Telnyx Call Control adapter.

Telnyx is command-driven rather than document-driven: instead of returning XML
that tells the carrier what to do, you receive a webhook per lifecycle event and
POST commands back. So `answer_document()` is a no-op here and the real work
happens in `on_event()` -- when the callee answers, we issue `streaming_start`
to open the bidirectional media socket.

Audio is PCMU (G.711 mu-law) at 8 kHz, the same wire format as Plivo and Twilio,
so nothing downstream changes.
"""

from __future__ import annotations

import base64
from typing import Any

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
API_BASE = "https://api.telnyx.com/v2"

# `call.hangup` carries a cause rather than a status, so the mapping happens here.
HANGUP_CAUSES = {
    "normal_clearing": CallStatus.COMPLETED,
    "user_busy": CallStatus.BUSY,
    "busy": CallStatus.BUSY,
    "timeout": CallStatus.NO_ANSWER,
    "no_answer": CallStatus.NO_ANSWER,
    "originator_cancel": CallStatus.CANCELED,
    "call_rejected": CallStatus.FAILED,
    "not_found": CallStatus.FAILED,
    "unspecified": CallStatus.FAILED,
}


class TelnyxTelephonyProvider(TelephonyProvider):
    name = "telnyx"
    answers_with_document = False

    def _headers(self) -> dict[str, str]:
        if not settings.telnyx_api_key:
            raise ProviderError(self.name, "TELNYX_API_KEY is not set")
        return {
            "Authorization": f"Bearer {settings.telnyx_api_key}",
            "Content-Type": "application/json",
        }

    async def _command(self, call_control_id: str, action: str, body: dict[str, Any]) -> None:
        url = f"{API_BASE}/calls/{call_control_id}/actions/{action}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"{action}: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderError(
                self.name, f"{action}: {response.status_code} {response.text[:300]}"
            )

    # --- lifecycle -----------------------------------------------------

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
        if not settings.telnyx_connection_id:
            raise ProviderError(self.name, "TELNYX_CONNECTION_ID is not set")

        body = {
            "to": to_number,
            "from": from_number or settings.telnyx_caller_id,
            "connection_id": settings.telnyx_connection_id,
            # Per-call webhook: overrides whatever the Call Control application
            # is configured with, so every call reports to its own URL.
            "webhook_url": status_url,
            "webhook_url_method": "POST",
            "timeout_secs": settings.ring_timeout_seconds,
            # Echoed back on every webhook, which is how we tie an event to a call.
            "client_state": base64.b64encode(call_id.encode()).decode(),
        }
        if record:
            body["record"] = "record-from-answer"
            body["record_channels"] = "dual"
            body["record_format"] = "mp3"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{API_BASE}/calls", headers=self._headers(), json=body
                )
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")

        data = response.json().get("data", {})
        call_control_id = data.get("call_control_id", "")
        log.info("telephony.originated", provider="telnyx", provider_call_id=call_control_id)
        return OriginateResult(provider_call_id=call_control_id)

    async def answer(self, provider_call_id: str) -> None:
        await self._command(provider_call_id, "answer", {})

    def is_inbound(self, payload: dict[str, Any]) -> bool:
        data = payload.get("data", payload)
        body = data.get("payload", {})
        return data.get("event_type") == "call.initiated" and body.get("direction") == "incoming"

    def inbound_details(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        body = payload.get("data", payload).get("payload", {})
        return (
            str(body.get("call_control_id", "")),
            str(body.get("from", "")),
            str(body.get("to", "")),
        )

    async def hangup(self, provider_call_id: str) -> None:
        await self._command(provider_call_id, "hangup", {})

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        await self._command(provider_call_id, "transfer", {"to": to_number})

    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        """Call Control has no answer document -- see `on_event`."""
        return ("{}", "application/json")

    async def on_event(self, event: TelephonyEvent, *, websocket_url: str) -> None:
        """Open the media stream once the callee picks up."""
        if event.type is not TelephonyEventType.ANSWERED or not event.provider_call_id:
            return
        await self._command(
            event.provider_call_id,
            "streaming_start",
            {
                "stream_url": websocket_url,
                "stream_track": "inbound_track",
                # Bidirectional is the whole point: without audio flowing back
                # on the same socket the agent cannot speak, and barge-in cannot
                # cancel what has already been sent.
                "stream_bidirectional_mode": "rtp",
                "stream_bidirectional_codec": "PCMU",
            },
        )
        log.info("telephony.stream_started", provider="telnyx", call=event.provider_call_id)

    # --- webhooks ------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent:
        data = payload.get("data", payload)
        event_type = str(data.get("event_type", ""))
        body = data.get("payload", {})
        call_control_id = str(body.get("call_control_id", ""))
        hangup_cause = body.get("hangup_cause")

        if event_type == "call.initiated":
            kind, status = TelephonyEventType.RINGING, CallStatus.RINGING
        elif event_type == "call.answered":
            kind, status = TelephonyEventType.ANSWERED, CallStatus.IN_PROGRESS
        elif event_type == "call.hangup":
            status = HANGUP_CAUSES.get(str(hangup_cause or "").lower(), CallStatus.COMPLETED)
            kind = (
                TelephonyEventType.COMPLETED
                if status is CallStatus.COMPLETED
                else TelephonyEventType.FAILED
            )
        else:
            # streaming.started, call.machine.detection.ended, and friends: noted
            # but not state-changing.
            kind, status = TelephonyEventType.UNKNOWN, None

        return TelephonyEvent(
            type=kind,
            provider_call_id=call_control_id,
            status=status,
            recording_url=(body.get("recording_urls") or {}).get("mp3"),
            hangup_cause=hangup_cause,
            raw=payload,
        )

    # --- media frames --------------------------------------------------

    def decode_media(self, message: dict[str, Any]) -> bytes | None:
        if message.get("event") != "media":
            return None
        media = message.get("media", {})
        # Only inbound audio is transcribed; echoing our own outbound track back
        # into STT would make the agent transcribe itself.
        if media.get("track") not in (None, "inbound"):
            return None
        payload = media.get("payload")
        return base64.b64decode(payload) if payload else None

    def encode_media(self, audio: bytes, stream_id: str | None) -> dict[str, Any]:
        frame: dict[str, Any] = {
            "event": "media",
            "media": {"payload": base64.b64encode(audio).decode()},
        }
        if stream_id:
            frame["stream_id"] = stream_id
        return frame

    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        message: dict[str, Any] = {"event": "clear"}
        if stream_id:
            message["stream_id"] = stream_id
        return message

    def stream_id_from(self, message: dict[str, Any]) -> str | None:
        return message.get("stream_id") or message.get("start", {}).get("stream_id")
