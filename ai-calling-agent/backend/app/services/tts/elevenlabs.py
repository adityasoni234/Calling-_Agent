"""ElevenLabs Flash — the quality tier.

Meaningfully more expensive per character than Cartesia or Aura, so it is
exposed as a per-agent choice rather than the default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.services.base import ProviderError
from app.services.tts.base import TTSProvider

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsTTSProvider(TTSProvider):
    name = "elevenlabs"

    async def stream(  # type: ignore[override]
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        if not settings.elevenlabs_api_key:
            raise ProviderError(self.name, "ELEVENLABS_API_KEY is not set")

        voice_id = voice_config.get("voice_id") or settings.tts_voice_id
        if not voice_id:
            raise ProviderError(self.name, "no voice_id configured for this agent")

        output_format = "ulaw_8000" if encoding == "mulaw" else f"pcm_{sample_rate}"
        url = f"{API_BASE}/{voice_id}/stream?output_format={output_format}"
        body = {
            "text": text,
            "model_id": voice_config.get("model") or settings.tts_model or "eleven_flash_v2_5",
            "voice_settings": {
                "stability": float(voice_config.get("stability", 0.5)),
                "similarity_boost": float(voice_config.get("similarity_boost", 0.75)),
                "speed": float(voice_config.get("speed", 1.0)),
            },
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                async with client.stream(
                    "POST", url, headers={"xi-api-key": settings.elevenlabs_api_key}, json=body
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode()[:300]
                        raise ProviderError(self.name, f"{response.status_code}: {detail}")
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc
