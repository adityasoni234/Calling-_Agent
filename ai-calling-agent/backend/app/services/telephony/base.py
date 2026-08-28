"""Telephony interface.

Deliberately shaped around bidirectional media streaming, because a provider
that can only play audio files cannot support barge-in and is therefore unusable
for this product regardless of price.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.call import CallStatus, UsageComponent
from app.services.base import UsageRecord


class TelephonyEventType(enum.StrEnum):
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class OriginateResult:
    provider_call_id: str
    status: CallStatus = CallStatus.INITIATED


@dataclass(slots=True)
class TelephonyEvent:
    type: TelephonyEventType
    provider_call_id: str
    status: CallStatus | None = None
    duration_seconds: int | None = None
    recording_url: str | None = None
    hangup_cause: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class TelephonyProvider(ABC):
    name: str = "base"
    # Wire format the provider streams. Both Plivo and Twilio use 8 kHz mu-law,
    # which Deepgram and Cartesia accept directly -- so no transcoding.
    sample_rate: int = 8000
    encoding: str = "mulaw"

    @abstractmethod
    async def originate(
        self, *, to_number: str, from_number: str, answer_url: str, status_url: str, call_id: str
    ) -> OriginateResult: ...

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> None: ...

    @abstractmethod
    async def transfer(self, provider_call_id: str, to_number: str) -> None: ...

    @abstractmethod
    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        """Return `(body, content_type)` telling the provider to open the media stream."""

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent: ...

    # --- media frames --------------------------------------------------

    @abstractmethod
    def decode_media(self, message: dict[str, Any]) -> bytes | None:
        """Extract inbound audio from a provider WebSocket message, if it has any."""

    @abstractmethod
    def encode_media(self, audio: bytes, stream_id: str | None) -> dict[str, Any]: ...

    @abstractmethod
    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        """Message that flushes already-sent audio -- the wire half of barge-in."""

    def stream_id_from(self, message: dict[str, Any]) -> str | None:
        return None

    def usage_for_call(self, duration_seconds: int, region: str | None = None) -> UsageRecord:
        return UsageRecord(
            component=UsageComponent.TELEPHONY,
            provider=self.name,
            unit="minute",
            quantity=round(duration_seconds / 60, 4),
            model=region,
        )
