"""OpenAI-compatible chat adapter.

Covers OpenAI itself and anything that speaks the same protocol -- Groq,
Together, OpenRouter, or a self-hosted vLLM -- so moving to self-hosted
inference later is an env change, not a code change.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.config import settings
from app.models.call import UsageComponent
from app.services.base import ProviderError, UsageRecord
from app.services.llm.base import LLMDelta, LLMMessage, LLMProvider


class OpenAICompatLLMProvider(LLMProvider):
    name = "openai"

    @property
    def _base_url(self) -> str:
        return (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not settings.openai_api_key:
            raise ProviderError(self.name, "OPENAI_API_KEY is not set")
        return {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    async def stream_chat(  # type: ignore[override]
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        model: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 300,
        cache_system: bool = True,
    ) -> AsyncIterator[LLMDelta]:
        chosen = model or settings.llm_model
        body = {
            "model": chosen,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }

        usage: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions", headers=self._headers(), json=body
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode()[:300]
                        raise ProviderError(self.name, f"{response.status_code}: {detail}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        event = json.loads(chunk)
                        if event.get("usage"):
                            usage = event["usage"]
                        for choice in event.get("choices", []):
                            text = choice.get("delta", {}).get("content") or ""
                            if text:
                                yield LLMDelta(text=text)
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        yield LLMDelta(
            done=True,
            usage=[
                UsageRecord(
                    UsageComponent.LLM,
                    self.name,
                    "token_in",
                    float(usage.get("prompt_tokens") or 0),
                    chosen,
                ),
                UsageRecord(
                    UsageComponent.LLM,
                    self.name,
                    "token_out",
                    float(usage.get("completion_tokens") or 0),
                    chosen,
                ),
            ],
        )

    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        model: str | None = None,
        max_tokens: int = 900,
    ) -> tuple[dict[str, Any], list[UsageRecord]]:
        chosen = model or settings.llm_model
        body = {
            "model": chosen,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": schema, "strict": False},
            },
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions", headers=self._headers(), json=body
                )
                if response.status_code >= 400:
                    raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        return json.loads(content), [
            UsageRecord(
                UsageComponent.LLM,
                self.name,
                "token_in",
                float(usage.get("prompt_tokens") or 0),
                chosen,
            ),
            UsageRecord(
                UsageComponent.LLM,
                self.name,
                "token_out",
                float(usage.get("completion_tokens") or 0),
                chosen,
            ),
        ]
