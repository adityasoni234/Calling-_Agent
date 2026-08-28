"""Large-language-model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.base import UsageRecord


@dataclass(slots=True)
class LLMMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(slots=True)
class LLMDelta:
    """A streamed fragment. Usage arrives on the final delta."""

    text: str = ""
    done: bool = False
    usage: list[UsageRecord] = field(default_factory=list)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def stream_chat(
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        model: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 300,
        cache_system: bool = True,
    ) -> AsyncIterator[LLMDelta]:
        """Stream a reply.

        `cache_system` marks the system prompt as a cacheable prefix. The persona
        block is byte-identical on every turn of every call for a given agent,
        so caching it is the single largest LLM cost lever available.
        """

    @abstractmethod
    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        model: str | None = None,
        max_tokens: int = 900,
    ) -> tuple[dict[str, Any], list[UsageRecord]]:
        """Return a JSON object matching `schema`. Callers validate with Pydantic."""
