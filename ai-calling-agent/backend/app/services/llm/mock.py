"""Deterministic stand-in LLM.

Produces plausible, state-aware replies without any API call, so tests and local
demos exercise the real orchestration path. It does no reasoning.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.models.call import UsageComponent
from app.services.base import UsageRecord
from app.services.llm.base import LLMDelta, LLMMessage, LLMProvider

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _estimate_tokens(text: str) -> float:
    return max(1.0, len(text) / 4)


class MockLLMProvider(LLMProvider):
    name = "mock"

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
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "").lower()

        if not messages:
            reply = "Namaste! Main aapki kaise madad kar sakta hoon?"
        elif any(word in last_user for word in ("bye", "thank", "dhanyavaad")):
            reply = "Thank you for your time. Have a great day!"
        elif "price" in last_user or "cost" in last_user or "kitna" in last_user:
            reply = "Pricing depends on your usage. Aapka monthly volume kitna hoga?"
        elif "budget" in last_user:
            reply = (
                "Samajh gaya. Budget ke hisaab se ek plan nikal sakte hain. "
                "Kab tak start karna chahenge?"
            )
        else:
            reply = "Ji bilkul. Aap apni requirement thoda detail mein bata sakte hain?"

        for word in reply.split(" "):
            await asyncio.sleep(0)
            yield LLMDelta(text=word + " ")

        prompt_tokens = _estimate_tokens(system) + sum(
            _estimate_tokens(m.content) for m in messages
        )
        yield LLMDelta(
            done=True,
            usage=[
                UsageRecord(UsageComponent.LLM, "mock", "token_in", prompt_tokens, "mock"),
                UsageRecord(
                    UsageComponent.LLM, "mock", "token_out", _estimate_tokens(reply), "mock"
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
        properties = (schema or {}).get("properties", {})

        # Agent blueprint: the builder asks for a persona, not call analysis.
        if "primary_objective" in properties:
            payload = {
                "name": "Riya",
                "role_title": "Sales Executive",
                "personality": "Warm, direct and never pushy.",
                "primary_objective": "Book a fifteen minute demo",
                "secondary_objectives": ["Find out which tool they use today"],
                "greeting": "Namaste, main Riya bol rahi hoon. Do minute baat kar sakte hain?",
                "qualification_questions": ["Abhi aap kaunsa platform use karte hain?"],
                "forbidden_rules": ["Never promise guaranteed returns"],
                "ending_rules": ["End once a demo is booked"],
                "objection_handling": [
                    {
                        "objection": "too expensive",
                        "response": "Chhote plan se shuru kar sakte hain.",
                    }
                ],
                "language": "auto",
            }
            usage = [
                UsageRecord(
                    UsageComponent.LLM, "mock", "token_in", _estimate_tokens(prompt), "mock"
                ),
                UsageRecord(
                    UsageComponent.LLM,
                    "mock",
                    "token_out",
                    _estimate_tokens(json.dumps(payload)),
                    "mock",
                ),
            ]
            return payload, usage

        lowered = prompt.lower()
        email = _EMAIL.search(prompt)
        interested = "interested" in lowered or "bilkul" in lowered
        payload = {
            "summary": "Customer discussed requirements and pricing; follow-up material requested.",
            "requirement": "Product information and pricing",
            "budget": "tight" if "budget" in lowered else "",
            "timeline": "",
            "interest_level": "medium" if interested else "low",
            "objections": ["budget"] if "budget" in lowered else [],
            "follow_up_required": bool(email) or interested,
            "follow_up_time": None,
            "lead_score": 60 if interested else 25,
            "email": email.group(0) if email else None,
            "outcome": "follow_up" if interested else "not_interested",
        }
        usage = [
            UsageRecord(UsageComponent.LLM, "mock", "token_in", _estimate_tokens(prompt), "mock"),
            UsageRecord(
                UsageComponent.LLM,
                "mock",
                "token_out",
                _estimate_tokens(json.dumps(payload)),
                "mock",
            ),
        ]
        return payload, usage
