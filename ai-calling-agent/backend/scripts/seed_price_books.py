"""Install the launch price books.

Three voice tiers from the commercial brief, plus messaging and AI lines so
nothing quotes "unpriced" on day one.

The voice numbers carry `assumed_cost` measured from this platform's own
calls, not a vendor's headline rate: $0.1147 for a connected minute once
Deepgram, Cartesia and Anthropic are counted alongside the carrier. That
matters because the $0.10 enterprise floor is *below* it. The floor is seeded
as a draft with the loss recorded, so publishing it is a decision someone
makes rather than an accident -- `PricingEngine.publish` refuses it without a
written reason.

    python -m scripts.seed_price_books

Re-runnable: it updates rules in place rather than duplicating them.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.price_book import (
    Billable,
    PriceBook,
    PriceBookStatus,
    PriceRule,
    RateKind,
    Rounding,
)

#: Measured on 127 real agent calls: carrier $0.0744 (including the per-call
#: minute rounding a carrier applies), Deepgram $0.0077, Cartesia $0.0208,
#: Claude Haiku $0.0118.
VOICE_COST = Decimal("0.1147")

#: Messaging rates are placeholders until the Twilio rate card is synced.
#: They are deliberately above plausible cost rather than guessed low: a rule
#: that under-prices is invisible, while one that over-prices gets corrected
#: by the first customer who reads their bill.
SMS_COST = Decimal("0.0075")
WHATSAPP_COST = Decimal("0.0050")

TIERS: list[tuple[str, str, str, bool]] = [
    # slug, name, voice rate, publish
    ("enterprise", "Enterprise floor", "0.10", False),
    ("standard", "Standard", "0.13", True),
    ("premium", "Premium managed", "0.15", False),
]


def _rules(voice_rate: str) -> list[dict]:
    return [
        {
            "billable": Billable.VOICE_OUTBOUND,
            "rate_kind": RateKind.PER_MINUTE,
            "rate": Decimal(voice_rate),
            "rounding": Rounding.UP_TO_INCREMENT,
            "increment_seconds": 60,
            "minimum_charge": Decimal(voice_rate),
            "assumed_cost": VOICE_COST,
            "notes": "Per connected minute, rounded up, as the carrier bills us.",
        },
        {
            "billable": Billable.VOICE_INBOUND,
            "rate_kind": RateKind.PER_MINUTE,
            "rate": Decimal(voice_rate) / 2,
            "rounding": Rounding.UP_TO_INCREMENT,
            "increment_seconds": 60,
            "assumed_cost": VOICE_COST / 2,
            "notes": "Inbound has no dial-out leg.",
        },
        {
            "billable": Billable.SMS_OUTBOUND,
            "rate_kind": RateKind.PER_UNIT,
            "rate": Decimal("0.02"),
            "rounding": Rounding.NONE,
            "assumed_cost": SMS_COST,
            "notes": "Per segment. A long or non-Latin message is several.",
        },
        {
            "billable": Billable.WHATSAPP_OUTBOUND,
            "rate_kind": RateKind.PER_UNIT,
            "rate": Decimal("0.015"),
            "rounding": Rounding.NONE,
            "assumed_cost": WHATSAPP_COST,
            "notes": "Free-form reply inside the 24-hour session window.",
        },
        {
            "billable": Billable.WHATSAPP_TEMPLATE,
            "rate_kind": RateKind.PER_UNIT,
            "rate": Decimal("0.035"),
            "rounding": Rounding.NONE,
            "assumed_cost": Decimal("0.0125"),
            "notes": "Business-initiated. Meta charges more for these.",
        },
        {
            # Inbound messages are not resold; priced at zero on purpose so
            # the engine reports "free", not "unpriced".
            "billable": Billable.SMS_INBOUND,
            "rate_kind": RateKind.FLAT,
            "rate": Decimal("0"),
            "rounding": Rounding.NONE,
            "assumed_cost": Decimal("0"),
            "notes": "Inbound is not charged to the customer.",
        },
        {
            "billable": Billable.WHATSAPP_INBOUND,
            "rate_kind": RateKind.FLAT,
            "rate": Decimal("0"),
            "rounding": Rounding.NONE,
            "assumed_cost": Decimal("0"),
            "notes": "Inbound is not charged to the customer.",
        },
        {
            # Bulk email is cents per thousand at every provider, so this is
            # priced per message in millionths rather than cents.
            "billable": Billable.EMAIL_OUTBOUND,
            "rate_kind": RateKind.PER_UNIT,
            "rate": Decimal("0.0008"),
            "rounding": Rounding.NONE,
            "assumed_cost": Decimal("0.0002"),
            "notes": "Per delivered email. Validation is charged separately.",
        },
        {
            "billable": Billable.EMAIL_VALIDATION,
            "rate_kind": RateKind.PER_UNIT,
            "rate": Decimal("0.0002"),
            "rounding": Rounding.NONE,
            "assumed_cost": Decimal("0.00005"),
            "notes": "Per address checked, whether or not it is then mailed.",
        },
        {
            "billable": Billable.RECORDING,
            "rate_kind": RateKind.PER_MINUTE,
            "rate": Decimal("0.005"),
            "rounding": Rounding.UP_TO_INCREMENT,
            "increment_seconds": 60,
            "assumed_cost": Decimal("0.0025"),
        },
        {
            "billable": Billable.TRANSCRIPTION,
            "rate_kind": RateKind.PER_MINUTE,
            "rate": Decimal("0.02"),
            "rounding": Rounding.PER_SECOND,
            "assumed_cost": Decimal("0.0077"),
        },
        {
            # Cost-markup: the model changes and its price with it, so a fixed
            # per-token rate would silently stop covering cost.
            "billable": Billable.AI_TOKENS,
            "rate_kind": RateKind.COST_MARKUP,
            "rate": Decimal("3.0"),
            "rounding": Rounding.NONE,
            "notes": "3x measured model cost, so a model change cannot undercut it.",
        },
        {
            "billable": Billable.PAYMENT_FEE,
            "rate_kind": RateKind.PERCENT,
            "rate": Decimal("2.9"),
            "fixed_fee": Decimal("0.30"),
            "rounding": Rounding.NONE,
            "notes": "Gateway fee passed through at cost.",
        },
    ]


async def main() -> None:
    now = datetime.now(UTC)

    async with SessionLocal() as db:
        for slug, name, voice_rate, publish in TIERS:
            found = await db.execute(select(PriceBook).where(PriceBook.slug == slug))
            book = found.scalars().first()
            if book is None:
                book = PriceBook(
                    slug=slug,
                    name=name,
                    version=1,
                    currency="USD",
                    is_default=(slug == "standard"),
                    status=PriceBookStatus.PUBLISHED if publish else PriceBookStatus.DRAFT,
                    effective_from=now if publish else None,
                    published_at=now if publish else None,
                    description=f"${voice_rate} per connected minute.",
                )
                db.add(book)
                await db.flush()
                verb = "created"
            else:
                verb = "updated"

            for spec in _rules(voice_rate):
                existing = await db.execute(
                    select(PriceRule).where(
                        PriceRule.price_book_id == book.id,
                        PriceRule.billable == spec["billable"],
                        PriceRule.region.is_(None),
                    )
                )
                rule = existing.scalars().first()
                if rule is None:
                    db.add(PriceRule(price_book_id=book.id, **spec))
                else:
                    for field, value in spec.items():
                        setattr(rule, field, value)

            margin = (Decimal(voice_rate) - VOICE_COST) / Decimal(voice_rate) * 100
            flag = "  <-- BELOW COST, left as draft" if margin < 0 else ""
            state = "published" if publish else "draft"
            print(
                f"  {verb:<8} {name:<18} ${voice_rate}/min  margin {margin:>6.1f}%  [{state}]{flag}"
            )

        await db.commit()

    print(
        f"\nVoice cost assumption: ${VOICE_COST}/connected minute, measured on this\n"
        f"platform's own calls (carrier + Deepgram + Cartesia + Claude Haiku).\n"
        f"Only the standard tier is published. The enterprise floor sells below\n"
        f"cost and publishing it needs a written reason."
    )


if __name__ == "__main__":
    asyncio.run(main())
