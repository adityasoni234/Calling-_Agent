"""Scripted STT, so the whole pipeline runs with no vendor account.

It is a mock and says so: it plays a fixed customer script, paced by how much
audio it has received, rather than transcribing anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.audio import frame_duration_ms
from app.models.call import UsageComponent
from app.services.base import UsageRecord
from app.services.stt.base import STTEvent, STTEventType, STTProvider, STTSession

DEFAULT_SCRIPT = [
    "Haan boliye, kaun bol raha hai?",
    "Achha, mujhe thoda detail mein bataiye, price kya hoga?",
    "Budget thoda tight hai, but interested hoon.",
    "Theek hai, aap mujhe WhatsApp pe bhej dijiye. My email is ravi@example.com.",
    "Ok thank you, bye.",
]


class MockSTTSession(STTSession):
    def __init__(self, script: list[str], audio_ms_per_turn: float = 2500) -> None:
        self._script = list(script)
        self._audio_ms_per_turn = audio_ms_per_turn
        self._audio_ms = 0.0
        self._elapsed_ms = 0.0
        self._queue: asyncio.Queue[STTEvent | None] = asyncio.Queue()
        self._closed = False

    async def send_audio(self, chunk: bytes) -> None:
        if self._closed:
            return
        duration = frame_duration_ms(chunk)
        self._audio_ms += duration
        self._elapsed_ms += duration
        if self._audio_ms >= self._audio_ms_per_turn and self._script:
            self._audio_ms = 0.0
            text = self._script.pop(0)
            await self._queue.put(STTEvent(STTEventType.SPEECH_STARTED))
            await self._queue.put(STTEvent(STTEventType.FINAL, text=text, confidence=0.95))
            await self._queue.put(STTEvent(STTEventType.UTTERANCE_END))

    async def events(self) -> AsyncIterator[STTEvent]:  # type: ignore[override]
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self._closed = True
        await self._queue.put(None)

    @property
    def usage(self) -> list[UsageRecord]:
        return [
            UsageRecord(
                component=UsageComponent.STT,
                provider="mock",
                unit="minute",
                quantity=round(self._elapsed_ms / 60000, 4),
                model="mock",
            )
        ]


class MockSTTProvider(STTProvider):
    name = "mock"

    def __init__(self, script: list[str] | None = None) -> None:
        self._script = script or DEFAULT_SCRIPT

    async def open(
        self, *, language: str, sample_rate: int = 8000, encoding: str = "mulaw"
    ) -> STTSession:
        return MockSTTSession(self._script)
