"""Anthropic Messages API adapter (streaming + JSON extraction).

The system prompt is sent as a cacheable prefix: the persona block is identical
on every turn of every call for a given agent, so caching it is the largest
single LLM cost lever in this product.
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

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def _usage_records(usage: dict[str, Any], model: str) -> list[UsageRecord]:
    cached = float(usage.get("cache_read_input_tokens") or 0)
    written = float(usage.get("cache_creation_input_tokens") or 0)
    records = [
        UsageRecord(
            UsageComponent.LLM,
            "anthropic",
            "token_in",
            float(usage.get("input_tokens") or 0),
            model,
        ),
        UsageRecord(
            UsageComponent.LLM,
            "anthropic",
            "token_out",
            float(usage.get("output_tokens") or 0),
            model,
        ),
    ]
    if cached:
        records.append(
            UsageRecord(UsageComponent.LLM, "anthropic", "token_cache_read", cached, model)
        )
    if written:
        records.append(
            UsageRecord(UsageComponent.LLM, "anthropic", "token_cache_write", written, model)
        )
    return records


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def _headers(self) -> dict[str, str]:
        if not settings.anthropic_api_key:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY is not set")
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        # Identity-linked keys are rejected without this; ordinary keys ignore it.
        if settings.anthropic_workspace_id:
            headers["anthropic-workspace-id"] = settings.anthropic_workspace_id
        return headers

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
        system_block: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_system:
            system_block[0]["cache_control"] = {"type": "ephemeral"}

        body = {
            "model": chosen,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_block,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }

        usage: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                async with client.stream(
                    "POST", API_URL, headers=self._headers(), json=body
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode()[:300]
                        raise ProviderError(
                            "anthropic",
                            f"{response.status_code}: {detail}",
                            retryable=response.status_code >= 500 or response.status_code == 429,
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:].strip())
                        kind = event.get("type")
                        if kind == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                            if text:
                                yield LLMDelta(text=text)
                        elif kind == "message_start":
                            usage.update(event.get("message", {}).get("usage", {}))
                        elif kind == "message_delta":
                            usage.update(event.get("usage", {}))
        except httpx.HTTPError as exc:
            raise ProviderError("anthropic", str(exc), retryable=True) from exc

        yield LLMDelta(done=True, usage=_usage_records(usage, chosen))

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
        # A forced tool call is the reliable way to get schema-shaped JSON back;
        # asking for JSON in prose and parsing it is where extraction breaks.
        body = {
            "model": chosen,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": "record",
                    "description": "Record the extracted call data.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "record"},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(API_URL, headers=self._headers(), json=body)
                if response.status_code >= 400:
                    raise ProviderError(
                        "anthropic", f"{response.status_code}: {response.text[:300]}"
                    )
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("anthropic", str(exc), retryable=True) from exc

        data: dict[str, Any] = {}
        for block in payload.get("content", []):
            if block.get("type") == "tool_use":
                data = block.get("input", {})
                break
        return data, _usage_records(payload.get("usage", {}), chosen)
