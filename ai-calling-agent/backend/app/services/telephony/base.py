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
    # True: the carrier fetches an XML document that answers the call and opens
    # the stream (Plivo, Twilio). False: the carrier is driven by commands and
    # expects only an acknowledgement (Telnyx Call Control).
    answers_with_document: bool = True
    # True when the vendor runs the conversation itself, so no media socket is
    # opened and our conversation manager, barge-in and prompt do not apply.
    # The platform still owns leads, campaigns, scoring and cost.
    runs_own_conversation: bool = False

    @abstractmethod
    async def originate(
        self,
        *,
        to_number: str,
        from_number: str,
        answer_url: str,
        status_url: str,
        call_id: str,
        record: bool = False,
    ) -> OriginateResult: ...

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> None: ...

    @abstractmethod
    async def transfer(self, provider_call_id: str, to_number: str) -> None: ...

    @abstractmethod
    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        """Return `(body, content_type)` telling the provider to open the media stream."""

    def bridge_document(
        self, *, to_number: str, caller_id: str, record: bool = False
    ) -> tuple[str, str]:
        """Document that connects the answered leg to `to_number`.

        Used for human-operated calls: we ring the operator first, and when they
        pick up the carrier fetches this and dials the lead. Ringing the operator
        first means the lead's phone only rings once someone is actually there.
        """
        raise NotImplementedError(f"{self.name} cannot bridge two legs")

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent: ...

    async def answer(self, provider_call_id: str) -> None:
        """Pick up an inbound call.

        Document-driven providers answer implicitly when they fetch the answer
        document, so this is a no-op for them.
        """
        return None

    def is_inbound(self, payload: dict[str, Any]) -> bool:
        """True when this webhook is a new inbound call we have never seen."""
        return False

    def inbound_details(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        """Return `(provider_call_id, from_number, to_number)` for an inbound call."""
        return "", "", ""

    async def on_event(self, event: TelephonyEvent, *, websocket_url: str) -> None:
        """React to a webhook by issuing provider commands.

        XML-driven providers (Plivo, Twilio) answer the call and open the media
        stream from the document returned by `answer_document()`, so they need
        nothing here. Command-driven providers (Telnyx Call Control) have no
        answer document at all -- they are told what to do event by event, which
        is what this hook is for. Default is a no-op.
        """
        return None

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
            region=region,
        )
