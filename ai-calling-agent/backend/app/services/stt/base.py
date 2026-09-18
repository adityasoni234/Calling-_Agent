"""Speech-to-text interface.

Streaming-first on purpose: a request/response STT interface cannot be
retrofitted into a low-latency one, and endpointing events are what make
barge-in cheap to implement.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.services.base import UsageRecord


class STTEventType(enum.StrEnum):
    SPEECH_STARTED = "speech_started"
    PARTIAL = "partial"
    FINAL = "final"
    UTTERANCE_END = "utterance_end"
    ERROR = "error"


@dataclass(slots=True)
class STTEvent:
    type: STTEventType
    text: str = ""
    confidence: float = 0.0
    language: str | None = None
    #: True only when the provider's endpointing says the speaker has finished.
    #: A FINAL without it is a mid-sentence segment the provider chose to close,
    #: and replying to one cuts the customer off.
    speech_final: bool = False


class STTSession(ABC):
    """One open transcription stream, for the duration of one call."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[STTEvent]: ...

    @abstractmethod
    async def close(self) -> None: ...

    @property
    @abstractmethod
    def usage(self) -> list[UsageRecord]: ...


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def open(
        self, *, language: str, sample_rate: int = 8000, encoding: str = "mulaw"
    ) -> STTSession: ...
