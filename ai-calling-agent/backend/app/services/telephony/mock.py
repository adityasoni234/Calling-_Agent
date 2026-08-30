"""In-process telephony, for tests and for running the stack with no vendor.

Frames use the same envelope shape as the real providers so the media loop is
exercised unchanged.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from app.models.call import CallStatus
from app.services.telephony.base import (
    OriginateResult,
    TelephonyEvent,
    TelephonyEventType,
    TelephonyProvider,
)


class MockTelephonyProvider(TelephonyProvider):
    name = "mock"

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
        return OriginateResult(provider_call_id=f"mock-{uuid.uuid4().hex[:12]}")

    async def hangup(self, provider_call_id: str) -> None:
        return None

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        return None

    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        return (f'{{"stream": "{websocket_url}"}}', "application/json")

    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent:
        status_map = {
            "ringing": (TelephonyEventType.RINGING, CallStatus.RINGING),
            "answered": (TelephonyEventType.ANSWERED, CallStatus.IN_PROGRESS),
            "completed": (TelephonyEventType.COMPLETED, CallStatus.COMPLETED),
            "failed": (TelephonyEventType.FAILED, CallStatus.FAILED),
            "no_answer": (TelephonyEventType.COMPLETED, CallStatus.NO_ANSWER),
            "busy": (TelephonyEventType.COMPLETED, CallStatus.BUSY),
        }
        event_type, status = status_map.get(
            str(payload.get("status", "")).lower(), (TelephonyEventType.UNKNOWN, None)
        )
        duration = payload.get("duration")
        return TelephonyEvent(
            type=event_type,
            provider_call_id=str(payload.get("call_id", "")),
            status=status,
            duration_seconds=int(duration) if duration is not None else None,
            recording_url=payload.get("recording_url"),
            raw=payload,
        )

    def decode_media(self, message: dict[str, Any]) -> bytes | None:
        if message.get("event") == "media":
            return base64.b64decode(message["media"]["payload"])
        return None

    def encode_media(self, audio: bytes, stream_id: str | None) -> dict[str, Any]:
        return {
            "event": "media",
            "streamId": stream_id,
            "media": {"payload": base64.b64encode(audio).decode()},
        }

    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        return {"event": "clear", "streamId": stream_id}

    def stream_id_from(self, message: dict[str, Any]) -> str | None:
        return message.get("streamId") or message.get("start", {}).get("streamId")
