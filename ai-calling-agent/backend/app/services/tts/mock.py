"""Silent TTS with realistic timing.

Emits mu-law silence at roughly natural speaking rate, so barge-in, silence
timers, and turn-taking can all be exercised without a vendor account.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.services.tts.base import TTSProvider

FRAME_MS = 20
CHARS_PER_SECOND = 14.0


class MockTTSProvider(TTSProvider):
    name = "mock"

    async def stream(  # type: ignore[override]
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        total_ms = max(FRAME_MS, (len(text) / CHARS_PER_SECOND) * 1000)
        frame_bytes = int(sample_rate * FRAME_MS / 1000)
        # 0xFF is mu-law silence.
        frame = b"\xff" * frame_bytes
        for _ in range(int(total_ms // FRAME_MS)):
            await asyncio.sleep(FRAME_MS / 1000)
            yield frame
