"""Deepgram Aura — cheap, fast, streams mu-law at telephony rates."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.base import ProviderError
from app.services.tts.base import TTSProvider

API_URL = "https://api.deepgram.com/v1/speak"


class DeepgramTTSProvider(TTSProvider):
    name = "deepgram"

    async def stream(  # type: ignore[override]
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        if not settings.deepgram_api_key:
            raise ProviderError(self.name, "DEEPGRAM_API_KEY is not set")

        params = {
            "model": voice_config.get("voice_id") or settings.tts_voice_id or "aura-2-thalia-en",
            "encoding": encoding,
            "sample_rate": str(sample_rate),
        }
        url = f"{API_URL}?{urlencode(params)}"
        headers = {
            "Authorization": f"Token {settings.deepgram_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                async with client.stream(
                    "POST", url, headers=headers, json={"text": text}
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode()[:300]
                        raise ProviderError(self.name, f"{response.status_code}: {detail}")
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc
