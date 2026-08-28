from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.core.config import settings
from app.models.call import UsageComponent
from app.services.base import ProviderError, UsageRecord
from app.services.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self) -> None:
        self.dimensions = settings.embedding_dim

    async def embed(self, texts: Sequence[str]) -> tuple[list[list[float]], list[UsageRecord]]:
        if not settings.openai_api_key:
            raise ProviderError(self.name, "OPENAI_API_KEY is not set")
        base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base}/embeddings",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": settings.embedding_model,
                        "input": list(texts),
                        "dimensions": self.dimensions,
                    },
                )
                if response.status_code >= 400:
                    raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        vectors = [item["embedding"] for item in sorted(payload["data"], key=lambda d: d["index"])]
        tokens = float(payload.get("usage", {}).get("prompt_tokens") or 0)
        return vectors, [
            UsageRecord(
                UsageComponent.EMBEDDING, self.name, "token_in", tokens, settings.embedding_model
            )
        ]
