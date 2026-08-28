"""Cartesia Sonic — low time-to-first-audio, streams mu-law directly.

Cancellation is what matters here: closing the response stream (which happens
when the consuming task is cancelled) stops synthesis mid-utterance, which is
the whole mechanism behind barge-in.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.services.base import ProviderError
from app.services.tts.base import TTSProvider

API_URL = "https://api.cartesia.ai/tts/sse"
API_VERSION = "2024-11-13"


class CartesiaTTSProvider(TTSProvider):
    name = "cartesia"

    async def stream(  # type: ignore[override]
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        if not settings.cartesia_api_key:
            raise ProviderError(self.name, "CARTESIA_API_KEY is not set")

        voice_id = voice_config.get("voice_id") or settings.tts_voice_id
        if not voice_id:
            raise ProviderError(self.name, "no voice_id configured for this agent")

        body = {
            "model_id": voice_config.get("model") or settings.tts_model or "sonic-2",
            "transcript": text,
            "voice": {"mode": "id", "id": voice_id},
            "language": voice_config.get("language", "en"),
            "output_format": {
                "container": "raw",
                "encoding": "pcm_mulaw" if encoding == "mulaw" else "pcm_s16le",
                "sample_rate": sample_rate,
            },
        }
        headers = {
            "X-API-Key": settings.cartesia_api_key,
            "Cartesia-Version": API_VERSION,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                async with client.stream("POST", API_URL, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode()[:300]
                        raise ProviderError(self.name, f"{response.status_code}: {detail}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:].strip())
                        if event.get("type") == "chunk" and event.get("data"):
                            yield base64.b64decode(event["data"])
                        elif event.get("type") == "done":
                            return
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc
