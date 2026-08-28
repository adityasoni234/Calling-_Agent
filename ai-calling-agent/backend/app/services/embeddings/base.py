from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.services.base import UsageRecord


class EmbeddingProvider(ABC):
    name: str = "base"
    dimensions: int = 1536

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> tuple[list[list[float]], list[UsageRecord]]: ...
