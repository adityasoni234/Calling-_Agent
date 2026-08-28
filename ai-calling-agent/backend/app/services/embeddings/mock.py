"""Deterministic hashed embeddings.

Not semantic, but stable and normalised -- similarity search returns consistent
results, so retrieval logic can be tested without an embedding bill.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from app.core.config import settings
from app.models.call import UsageComponent
from app.services.base import UsageRecord
from app.services.embeddings.base import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    name = "mock"

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.embedding_dim

    async def embed(self, texts: Sequence[str]) -> tuple[list[list[float]], list[UsageRecord]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in text.lower().split():
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[index] += sign
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])

        usage = [
            UsageRecord(
                UsageComponent.EMBEDDING,
                "mock",
                "token_in",
                sum(max(1.0, len(t) / 4) for t in texts),
                "mock",
            )
        ]
        return vectors, usage
