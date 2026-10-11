"""Re-denominate the credit packages into USD.

Credits are one US cent of list price again, and the price book -- not the
credit unit -- now sets what a call costs. The packages carry the correction
that the earlier INR move was standing in for.

Sized against the published standard tier, $0.13 per connected minute, so the
minutes figure on each card is the real one. Volume discount runs from a small
premium on the smallest pack to about 20% off the largest, which is an
ordinary ladder and profitable at every rung: a credit costs us about a third
of a cent to honour at the seeded 3x markup.

    python -m scripts.reprice_packages_usd

Safe to re-run. Refuses outright if any package has ever been bought for real
money, because changing what a sold package contained would rewrite history.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.package import CreditPackage, Order, OrderStatus

#: The published voice rate, in credits per minute. 100 credits == $1.
VOICE_CREDITS_PER_MINUTE = 13

#: slug -> (name, price in USD cents, base credits, bonus credits)
PACKAGES: dict[str, tuple[str, int, int, int]] = {
    "trial-topup": ("Trial top-up", 500, 400, 0),
    "starter": ("Starter", 2500, 2300, 200),
    "growth": ("Growth", 10000, 9500, 1000),
    "scale": ("Scale", 25000, 24000, 4000),
}


async def main() -> None:
    async with SessionLocal() as db:
        sold = await db.execute(
            select(Order).where(
                Order.status == OrderStatus.PAID, Order.provider.notin_(["simulated"])
            )
        )
        real = list(sold.scalars())
        if real:
            print(
                f"Refusing: {len(real)} package(s) have been bought for real money.\n"
                "Re-pricing them would change what someone already paid for.\n"
                "Create new packages and retire the old ones instead."
            )
            return

        print(f"  {'package':<14}{'price':>9}{'credits':>9}{'minutes':>9}{'$/min':>8}{'margin':>8}")
        for slug, (name, cents, base, bonus) in PACKAGES.items():
            found = await db.execute(select(CreditPackage).where(CreditPackage.slug == slug))
            package = found.scalars().first()
            if package is None:
                continue

            package.name = name
            package.price_minor = cents
            package.currency = "USD"
            # US customers are not charged Indian GST; tax is applied per
            # customer at checkout, not baked into a USD list price.
            package.tax_bps = 0
            package.base_credits = base
            package.bonus_credits = bonus

            credits = base + bonus
            minutes = credits / VOICE_CREDITS_PER_MINUTE
            price = Decimal(cents) / 100
            per_min = price / Decimal(minutes)
            # A credit costs us about a third of a cent at the seeded 3x markup.
            cost = Decimal(credits) / 100 / 3
            margin = (price - cost) / price * 100

            package.description = f"About {minutes:.0f} minutes of AI calling" + (
                f". Includes {bonus:,} bonus credits." if bonus else "."
            )
            print(
                f"  {name:<14}{'$' + str(price):>9}{credits:>9,}"
                f"{minutes:>9.0f}{'$' + f'{per_min:.3f}':>8}{margin:>7.0f}%"
            )

        await db.commit()
    print("\nCredits are one US cent of list price. The price book sets the rate.")


if __name__ == "__main__":
    asyncio.run(main())
