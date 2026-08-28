"""Provider selection.

One place decides which vendor each capability uses, driven entirely by
environment variables. Nothing outside this module imports a concrete adapter,
which is what keeps providers interchangeable.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.mock import MockEmbeddingProvider
from app.services.embeddings.openai import OpenAIEmbeddingProvider
from app.services.llm.anthropic import AnthropicLLMProvider
from app.services.llm.base import LLMProvider
from app.services.llm.mock import MockLLMProvider
from app.services.llm.openai_compat import OpenAICompatLLMProvider
from app.services.stt.base import STTProvider
from app.services.stt.deepgram import DeepgramSTTProvider
from app.services.stt.mock import MockSTTProvider
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.mock import MockTelephonyProvider
from app.services.telephony.plivo import PlivoTelephonyProvider
from app.services.telephony.twilio import TwilioTelephonyProvider
from app.services.tts.base import TTSProvider
from app.services.tts.cartesia import CartesiaTTSProvider
from app.services.tts.deepgram import DeepgramTTSProvider
from app.services.tts.elevenlabs import ElevenLabsTTSProvider
from app.services.tts.mock import MockTTSProvider

TELEPHONY: dict[str, Callable[[], TelephonyProvider]] = {
    "mock": MockTelephonyProvider,
    "plivo": PlivoTelephonyProvider,
    "twilio": TwilioTelephonyProvider,
}

STT: dict[str, Callable[[], STTProvider]] = {
    "mock": MockSTTProvider,
    "deepgram": DeepgramSTTProvider,
}

LLM: dict[str, Callable[[], LLMProvider]] = {
    "mock": MockLLMProvider,
    "anthropic": AnthropicLLMProvider,
    "openai": OpenAICompatLLMProvider,
}

TTS: dict[str, Callable[[], TTSProvider]] = {
    "mock": MockTTSProvider,
    "cartesia": CartesiaTTSProvider,
    "deepgram": DeepgramTTSProvider,
    "elevenlabs": ElevenLabsTTSProvider,
}

EMBEDDINGS: dict[str, Callable[[], EmbeddingProvider]] = {
    "mock": MockEmbeddingProvider,
    "openai": OpenAIEmbeddingProvider,
}


def _resolve(table: dict[str, Callable[[], Any]], name: str, kind: str) -> Any:
    factory = table.get(name.lower())
    if factory is None:
        raise AppError(
            f"Unknown {kind} provider '{name}'. Available: {', '.join(sorted(table))}",
            code="unknown_provider",
        )
    return factory()


@lru_cache(maxsize=8)
def get_telephony(name: str | None = None) -> TelephonyProvider:
    return _resolve(TELEPHONY, name or settings.telephony_provider, "telephony")


@lru_cache(maxsize=8)
def get_stt(name: str | None = None) -> STTProvider:
    return _resolve(STT, name or settings.stt_provider, "STT")


@lru_cache(maxsize=8)
def get_llm(name: str | None = None) -> LLMProvider:
    return _resolve(LLM, name or settings.llm_provider, "LLM")


@lru_cache(maxsize=8)
def get_tts(name: str | None = None) -> TTSProvider:
    return _resolve(TTS, name or settings.tts_provider, "TTS")


@lru_cache(maxsize=8)
def get_embeddings(name: str | None = None) -> EmbeddingProvider:
    return _resolve(EMBEDDINGS, name or settings.embedding_provider, "embedding")


def provider_status() -> dict[str, dict[str, Any]]:
    """What is configured and whether its credentials are actually present.

    Surfaced in Settings so misconfiguration is visible before a call fails,
    and never exposes the key values themselves.
    """
    checks = {
        "telephony": (
            settings.telephony_provider,
            {
                "plivo": bool(settings.plivo_auth_id and settings.plivo_auth_token),
                "twilio": bool(settings.twilio_account_sid and settings.twilio_auth_token),
                "mock": True,
            },
            sorted(TELEPHONY),
        ),
        "stt": (
            settings.stt_provider,
            {"deepgram": bool(settings.deepgram_api_key), "mock": True},
            sorted(STT),
        ),
        "llm": (
            settings.llm_provider,
            {
                "anthropic": bool(settings.anthropic_api_key),
                "openai": bool(settings.openai_api_key),
                "mock": True,
            },
            sorted(LLM),
        ),
        "tts": (
            settings.tts_provider,
            {
                "cartesia": bool(settings.cartesia_api_key),
                "deepgram": bool(settings.deepgram_api_key),
                "elevenlabs": bool(settings.elevenlabs_api_key),
                "mock": True,
            },
            sorted(TTS),
        ),
        "embeddings": (
            settings.embedding_provider,
            {"openai": bool(settings.openai_api_key), "mock": True},
            sorted(EMBEDDINGS),
        ),
    }

    return {
        kind: {
            "selected": selected,
            "configured": credentials.get(selected.lower(), False),
            "is_mock": selected.lower() == "mock",
            "available": available,
        }
        for kind, (selected, credentials, available) in checks.items()
    }
