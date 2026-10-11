"""Install the AI-stack rates: speech-to-text, text-to-speech and the LLM.

Only telephony was ever priced. The cost engine records STT, TTS and LLM usage
faithfully but refuses to price a line it has no verified rate for, so every
agent call was flagged `cost_incomplete` and billed for its phone leg alone --
about 65% of what it actually cost to run.

These are list prices read from each vendor's public pricing page. They are
typed in rather than fetched, because none of the three publishes a pricing
API the way Twilio does, so `source_url` points at the page a human can check
and `verified_at` records when a human last did.

    python -m scripts.import_ai_rates

Re-run it after a vendor changes prices; it updates rows in place.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.pricing import PricingRate

#: (component, provider, model, unit, rate_usd, source_url)
#:
#: Units follow UNIT_DIVISOR in the cost service: `_1k` rates are per thousand.
#: A model of None matches any model for that provider, so a rate exists even
#: if someone switches model without updating this file.
RATES: list[tuple[str, str, str | None, str, float, str]] = [
    # Deepgram Nova, streaming, pay-as-you-go.
    ("stt", "deepgram", None, "minute", 0.0077, "https://deepgram.com/pricing"),
    # Cartesia Sonic. Billed per character; the pro plan works out near this.
    ("tts", "cartesia", None, "character_1k", 0.030, "https://cartesia.ai/pricing"),
    # Claude Haiku 4.5: $1 per million in, $5 per million out.
    ("llm", "anthropic", "claude-haiku-4-5", "token_in_1k", 0.001, "https://claude.com/pricing"),
    ("llm", "anthropic", "claude-haiku-4-5", "token_out_1k", 0.005, "https://claude.com/pricing"),
    # Fallbacks, so a model switch still prices instead of silently going free.
    ("llm", "anthropic", None, "token_in_1k", 0.003, "https://claude.com/pricing"),
    ("llm", "anthropic", None, "token_out_1k", 0.015, "https://claude.com/pricing"),
    # Embeddings for the knowledge base. Tiny, but a gap is still a gap.
    ("embedding", "openai", None, "token_1k", 0.00002, "https://openai.com/api/pricing"),
]


async def main() -> None:
    now = datetime.now(UTC)
    added = updated = 0

    async with SessionLocal() as db:
        for component, provider, model, unit, rate, source in RATES:
            query = select(PricingRate).where(
                PricingRate.component == component,
                PricingRate.provider == provider,
                PricingRate.unit == unit,
                PricingRate.organization_id.is_(None),
                PricingRate.model.is_(None) if model is None else PricingRate.model == model,
            )
            existing = (await db.execute(query)).scalars().first()

            if existing is None:
                db.add(
                    PricingRate(
                        component=component,
                        provider=provider,
                        model=model,
                        unit=unit,
                        rate=rate,
                        currency="USD",
                        source_url=source,
                        verified_at=now,
                        is_active=True,
                    )
                )
                added += 1
                mark = "+"
            else:
                existing.rate = rate
                existing.source_url = source
                existing.verified_at = now
                existing.is_active = True
                updated += 1
                mark = "~"

            label = f"{component}/{provider}" + (f"/{model}" if model else "")
            print(f"  {mark} {label:<42} {rate:>12.6f} USD per {unit}")

        await db.commit()

    print(f"\n{added} added, {updated} updated.")


if __name__ == "__main__":
    asyncio.run(main())
