"""Text-to-speech interface.

Mid-utterance cancellation is a hard requirement, not an optimisation: without
it the agent talks over the customer. Adapters stream from an async generator,
so cancelling the consuming task closes the upstream connection immediately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.models.call import UsageComponent
from app.services.base import UsageRecord


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def stream(
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        """Yield audio frames in the telephony wire format."""

    def usage_for(self, text: str, voice_config: dict[str, Any]) -> UsageRecord:
        return UsageRecord(
            component=UsageComponent.TTS,
            provider=self.name,
            unit="character",
            quantity=float(len(text)),
            model=str(voice_config.get("model") or voice_config.get("voice_id") or ""),
        )
