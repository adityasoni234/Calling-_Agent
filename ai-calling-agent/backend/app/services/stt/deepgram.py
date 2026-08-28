"""Deepgram streaming ASR.

Chosen as the default because it returns interim results plus explicit
`SpeechStarted` / `UtteranceEnd` endpointing events -- barge-in needs a signal
the moment the customer opens their mouth, not after a final transcript.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import websockets

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call import UsageComponent
from app.services.base import ProviderError, UsageRecord
from app.services.stt.base import STTEvent, STTEventType, STTProvider, STTSession

log = get_logger(__name__)
DEEPGRAM_WS = "wss://api.deepgram.com/v1/listen"


class DeepgramSTTSession(STTSession):
    def __init__(self, connection: websockets.ClientConnection, model: str) -> None:
        self._ws = connection
        self._model = model
        self._audio_ms = 0.0
        self._closed = False

    async def send_audio(self, chunk: bytes) -> None:
        if self._closed:
            return
        self._audio_ms += len(chunk) / settings.audio_sample_rate * 1000
        try:
            await self._ws.send(chunk)
        except websockets.ConnectionClosed as exc:
            raise ProviderError("deepgram", "audio socket closed", retryable=True) from exc

    async def events(self) -> AsyncIterator[STTEvent]:  # type: ignore[override]
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                payload = json.loads(raw)
                kind = payload.get("type")

                if kind == "SpeechStarted":
                    yield STTEvent(STTEventType.SPEECH_STARTED)
                elif kind == "UtteranceEnd":
                    yield STTEvent(STTEventType.UTTERANCE_END)
                elif kind == "Results":
                    alternative = payload.get("channel", {}).get("alternatives", [{}])[0]
                    text = (alternative.get("transcript") or "").strip()
                    if not text:
                        continue
                    is_final = bool(payload.get("is_final")) or bool(payload.get("speech_final"))
                    yield STTEvent(
                        STTEventType.FINAL if is_final else STTEventType.PARTIAL,
                        text=text,
                        confidence=float(alternative.get("confidence") or 0.0),
                        language=alternative.get("language"),
                    )
        except websockets.ConnectionClosed:
            return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        await self._ws.close()

    @property
    def usage(self) -> list[UsageRecord]:
        return [
            UsageRecord(
                UsageComponent.STT,
                "deepgram",
                "minute",
                round(self._audio_ms / 60000, 4),
                self._model,
            )
        ]


class DeepgramSTTProvider(STTProvider):
    name = "deepgram"

    async def open(
        self, *, language: str, sample_rate: int = 8000, encoding: str = "mulaw"
    ) -> STTSession:
        if not settings.deepgram_api_key:
            raise ProviderError("deepgram", "DEEPGRAM_API_KEY is not set")

        params = {
            "model": settings.stt_model,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
            "channels": "1",
            "language": language,
            "punctuate": "true",
            "smart_format": "true",
            # Interim results and endpointing are what barge-in is built on.
            "interim_results": "true",
            "vad_events": "true",
            "endpointing": "300",
            "utterance_end_ms": "1000",
        }
        url = f"{DEEPGRAM_WS}?{urlencode(params)}"
        try:
            connection = await asyncio.wait_for(
                websockets.connect(
                    url,
                    additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
                    ping_interval=5,
                ),
                timeout=8,
            )
        except (TimeoutError, OSError, websockets.WebSocketException) as exc:
            raise ProviderError("deepgram", f"connect failed: {exc}", retryable=True) from exc

        log.info("stt.connected", provider="deepgram", model=settings.stt_model)
        return DeepgramSTTSession(connection, settings.stt_model)
