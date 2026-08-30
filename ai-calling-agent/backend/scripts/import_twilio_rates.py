"""Import verified telephony rates from Twilio's own Pricing API.

Rates come from the vendor's live API rather than being typed in by hand, so
`source_url` and `verified_at` are genuinely accurate. Re-run it whenever prices
change -- it updates existing rows in place rather than duplicating them.

    python -m scripts.import_twilio_rates --regions IN,US,GB,AE,SG,AU
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.pricing import PricingRate

PRICING_API = "https://pricing.twilio.com/v1/Voice/Countries"


async def fetch_rate(client: httpx.AsyncClient, region: str) -> tuple[float, str] | None:
    """Return `(price_per_minute, friendly_name)` for the region's mobile route."""
    response = await client.get(f"{PRICING_API}/{region}")
    if response.status_code >= 400:
        print(f"  {region}: HTTP {response.status_code}", file=sys.stderr)
        return None

    payload = response.json()
    prices = payload.get("outbound_prefix_prices") or []
    if not prices:
        print(f"  {region}: no outbound prices published", file=sys.stderr)
        return None

    # Prefer the mobile route: it is what a lead list actually dials.
    mobile = [p for p in prices if "mobile" in (p.get("friendly_name") or "").lower()]
    row = (mobile or prices)[0]
    return float(row["current_price"]), str(row.get("friendly_name") or region)


async def run(regions: list[str]) -> int:
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        print("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set", file=sys.stderr)
        return 1

    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    verified_at = datetime.now(UTC)

    async with SessionLocal() as db:
        async with httpx.AsyncClient(auth=auth, timeout=30) as client:
            written = 0
            for region in regions:
                result = await fetch_rate(client, region)
                if result is None:
                    continue
                price, label = result

                existing = (
                    (
                        await db.execute(
                            select(PricingRate).where(
                                PricingRate.organization_id.is_(None),
                                PricingRate.component == "telephony",
                                PricingRate.provider == "twilio",
                                PricingRate.unit == "minute",
                                PricingRate.region == region,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )

                if existing:
                    existing.rate = price
                    existing.verified_at = verified_at
                    existing.is_active = True
                else:
                    db.add(
                        PricingRate(
                            # Vendor rates are account-wide, not tenant-specific.
                            organization_id=None,
                            component="telephony",
                            provider="twilio",
                            unit="minute",
                            rate=price,
                            currency="USD",
                            region=region,
                            source_url=f"{PRICING_API}/{region}",
                            verified_at=verified_at,
                        )
                    )
                written += 1
                print(f"  {region:<4} ${price}/min   {label[:44]}")

            await db.commit()

    print(f"\n{written} global rate(s) imported.")
    print("Other components (STT, LLM, TTS) have no machine-readable rate card —")
    print("enter those by hand in Settings -> Pricing, with the page you read them on.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Twilio voice rates")
    parser.add_argument(
        "--regions",
        default="IN,US,GB,AE,SG,AU,CA,DE",
        help="Comma-separated ISO country codes to import.",
    )
    args = parser.parse_args()
    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    return asyncio.run(run(regions))


if __name__ == "__main__":
    raise SystemExit(main())
