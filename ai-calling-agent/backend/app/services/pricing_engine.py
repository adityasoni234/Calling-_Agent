"""What a billable action costs the customer.

The single place a customer-facing price is computed. Call sites ask for a
`Quote` and never do the arithmetic themselves -- a price calculated in a
React component is a price a customer can change.

Three ideas carry the file:

**Resolution order is explicit.** A customer's negotiated override beats their
own price book, which beats the platform default. Resolving this implicitly
(nearest match, most specific wins) made it impossible to answer "why was this
call charged that?".

**A quote is a receipt, not a number.** `Quote` carries the rule it came from,
the provider cost it was compared against, and the margin. The charge stored
on a call references the rule id, so a price change later cannot rewrite what
the call cost.

**Missing cost is stated, never assumed.** If a component has no verified rate
the quote is marked incomplete and the margin is None. A confident wrong
margin is worse than a visible gap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import (
    ZERO,
    billable_minutes,
    margin_percent,
    quantize_cost,
    to_decimal,
)
from app.core.times import as_utc
from app.models.price_book import (
    Billable,
    PriceBook,
    PriceBookStatus,
    PriceOverride,
    PriceRule,
    RateKind,
    Rounding,
)

#: Launch defaults, in USD. Editable through the admin; these are only what a
#: fresh install starts with.
DEFAULT_VOICE_PLANS: dict[str, Decimal] = {
    "enterprise": Decimal("0.10"),
    "standard": Decimal("0.13"),
    "premium": Decimal("0.15"),
}


class BelowCost(Exception):
    """Publishing would sell a known-cost item for less than it costs.

    Not a validation error: selling below cost is sometimes a deliberate
    commercial decision. It just has to be a decision someone recorded, which
    is what `below_cost_reason` is for.
    """

    def __init__(self, billable: str, price: Decimal, cost: Decimal) -> None:
        self.billable, self.price, self.cost = billable, price, cost
        super().__init__(
            f"{billable} priced at {price} but costs {cost} (losing {cost - price} per unit)"
        )


@dataclass
class Quote:
    """What we will charge, and why."""

    billable: Billable
    charge: Decimal
    #: What the quantity resolved to after rounding -- billed minutes, not
    #: wall-clock ones. Shown to the customer so a 17-second call billed as a
    #: minute is explained rather than disputed.
    billed_quantity: Decimal
    unit: str
    provider_cost: Decimal = ZERO
    rule_id: uuid.UUID | None = None
    price_book_id: uuid.UUID | None = None
    source: str = "default"
    #: True when some cost component had no verified rate. The margin is then
    #: unknowable and must be displayed as "Cost incomplete".
    cost_incomplete: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def gross_profit(self) -> Decimal | None:
        """Kept to the millionth, not the cent.

        A connected minute earns fractions of a cent over cost. Rounding each
        call's profit to two places discards most of it, and the discarded
        part is exactly the margin the business runs on.
        """
        if self.cost_incomplete:
            return None
        return quantize_cost(self.charge - self.provider_cost)

    @property
    def gross_margin_percent(self) -> Decimal | None:
        if self.cost_incomplete:
            return None
        return margin_percent(self.charge, self.provider_cost)

    def as_dict(self) -> dict:
        profit, margin = self.gross_profit, self.gross_margin_percent
        return {
            "billable": str(self.billable),
            "customer_charge_usd": str(self.charge),
            "provider_cost_usd": str(quantize_cost(self.provider_cost)),
            "gross_profit_usd": None if profit is None else str(profit),
            "gross_margin_percent": None if margin is None else str(margin),
            "billed_quantity": str(self.billed_quantity),
            "unit": self.unit,
            "cost_incomplete": self.cost_incomplete,
            "price_rule_id": str(self.rule_id) if self.rule_id else None,
            "source": self.source,
            "notes": self.notes,
        }


class PricingEngine:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- resolution ----------------------------------------------------

    async def _override(
        self, organization_id: uuid.UUID | None, billable: Billable, region: str | None
    ) -> PriceOverride | None:
        """A negotiated price for this one customer, if any and still valid."""
        if organization_id is None:
            return None
        now = datetime.now(UTC)
        rows = await self.db.execute(
            select(PriceOverride).where(
                PriceOverride.organization_id == organization_id,
                PriceOverride.billable == billable,
                PriceOverride.is_active.is_(True),
            )
        )
        candidates = [
            o
            for o in rows.scalars()
            if o.expires_at is None or as_utc(o.expires_at) > now
            if o.region in (region, None)
        ]
        # A rate for the destination country beats a global one.
        candidates.sort(key=lambda o: o.region is None)
        return candidates[0] if candidates else None

    async def _rule(
        self, organization_id: uuid.UUID | None, billable: Billable, region: str | None
    ) -> tuple[PriceRule, PriceBook] | None:
        """The customer's own published book first, then the platform default."""
        now = datetime.now(UTC)

        async def _books(org: uuid.UUID | None) -> list[PriceBook]:
            rows = await self.db.execute(
                select(PriceBook).where(
                    PriceBook.organization_id == org,
                    PriceBook.status == PriceBookStatus.PUBLISHED,
                )
            )
            live = [
                b
                for b in rows.scalars()
                if (as_utc(b.effective_from) is None or as_utc(b.effective_from) <= now)
                and (as_utc(b.effective_to) is None or as_utc(b.effective_to) > now)
            ]
            # Newest version wins when two are effective at once.
            live.sort(key=lambda b: b.version, reverse=True)
            return live

        for books in (await _books(organization_id), await _books(None)):
            for book in books:
                rows = await self.db.execute(
                    select(PriceRule).where(
                        PriceRule.price_book_id == book.id,
                        PriceRule.billable == billable,
                    )
                )
                rules = [r for r in rows.scalars() if r.region in (region, None)]
                rules.sort(key=lambda r: r.region is None)
                if rules:
                    return rules[0], book
        return None

    # --- quoting -------------------------------------------------------

    def _apply(
        self, rule: PriceRule | PriceOverride, quantity: Decimal, provider_cost: Decimal
    ) -> Decimal:
        """Turn a rule plus a quantity into money."""
        rate = to_decimal(rule.rate)
        kind = rule.rate_kind

        if kind == RateKind.FLAT:
            charge = rate
        elif kind == RateKind.COST_MARKUP:
            charge = provider_cost * rate
        elif kind == RateKind.PERCENT:
            charge = provider_cost * rate / Decimal(100)
        elif kind == RateKind.TIERED:
            charge = self._tiered(rule, quantity)
        else:  # PER_MINUTE and PER_UNIT differ only in how quantity was derived
            charge = rate * quantity

        charge += to_decimal(getattr(rule, "fixed_fee", None))
        minimum = getattr(rule, "minimum_charge", None)
        if minimum is not None and quantity > ZERO:
            charge = max(charge, to_decimal(minimum))
        # Micro precision, not cents. A single charge is one line among
        # thousands on an invoice; rounding each to a cent both loses money
        # and distorts the margin -- a $0.0342 charge rounded to $0.03 reports
        # 62% where the rule actually yields 66.67%. Cents happen once, on the
        # invoice total.
        return quantize_cost(charge)

    @staticmethod
    def _tiered(rule: PriceRule | PriceOverride, quantity: Decimal) -> Decimal:
        """Graduated tiers: each band is charged at its own rate.

        Not "the whole volume at the band's rate" -- that makes the bill drop
        as usage rises at every boundary, which customers notice.
        """
        tiers = sorted(
            getattr(rule, "tiers", None) or [],
            key=lambda t: to_decimal(t.get("up_to") or Decimal("Infinity")),
        )
        if not tiers:
            return to_decimal(rule.rate) * quantity

        charge, consumed = ZERO, ZERO
        for tier in tiers:
            cap = tier.get("up_to")
            ceiling = quantity if cap is None else min(quantity, to_decimal(cap))
            band = ceiling - consumed
            if band <= ZERO:
                continue
            charge += band * to_decimal(tier.get("rate"))
            consumed = ceiling
            if consumed >= quantity:
                break
        if consumed < quantity:  # beyond the last capped tier
            charge += (quantity - consumed) * to_decimal(tiers[-1].get("rate"))
        return charge

    @staticmethod
    def _quantity(
        rule: PriceRule | PriceOverride, *, seconds: int | None, units: Decimal | None
    ) -> tuple[Decimal, str]:
        if rule.rate_kind == RateKind.PER_MINUTE:
            rounding = getattr(rule, "rounding", Rounding.UP_TO_INCREMENT)
            increment = getattr(rule, "increment_seconds", 60) or 60
            if rounding == Rounding.PER_SECOND:
                return quantize_cost(to_decimal(seconds or 0) / 60), "minutes"
            return billable_minutes(seconds, increment_seconds=increment), "minutes"
        return to_decimal(units if units is not None else 0), "units"

    async def quote(
        self,
        *,
        billable: Billable,
        organization_id: uuid.UUID | None = None,
        region: str | None = None,
        seconds: int | None = None,
        units: Decimal | None = None,
        provider_cost: Decimal | None = None,
        cost_incomplete: bool = False,
    ) -> Quote:
        """Price one billable action.

        `provider_cost` is what we measured, already in USD. `cost_incomplete`
        says a component of it had no verified rate, which makes the margin
        unknowable rather than zero.
        """
        cost = quantize_cost(provider_cost)

        override = await self._override(organization_id, billable, region)
        if override is not None:
            quantity, unit = self._quantity(override, seconds=seconds, units=units)
            return Quote(
                billable=billable,
                charge=self._apply(override, quantity, cost),
                billed_quantity=quantity,
                unit=unit,
                provider_cost=cost,
                rule_id=override.id,
                source="override",
                cost_incomplete=cost_incomplete,
                notes=[f"Negotiated rate: {override.reason}"],
            )

        found = await self._rule(organization_id, billable, region)
        if found is None:
            # No rule is not free. Refusing to guess keeps an unpriced
            # product visible instead of quietly giving it away.
            return Quote(
                billable=billable,
                charge=ZERO,
                billed_quantity=ZERO,
                unit="units",
                provider_cost=cost,
                source="unpriced",
                cost_incomplete=True,
                notes=["No published price rule for this item"],
            )

        rule, book = found
        quantity, unit = self._quantity(rule, seconds=seconds, units=units)
        return Quote(
            billable=billable,
            charge=self._apply(rule, quantity, cost),
            billed_quantity=quantity,
            unit=unit,
            provider_cost=cost,
            rule_id=rule.id,
            price_book_id=book.id,
            source="override" if book.organization_id else "platform",
            cost_incomplete=cost_incomplete,
        )

    # --- publishing ----------------------------------------------------

    async def check_publishable(self, book: PriceBook) -> list[BelowCost]:
        """Which rules in this book would sell below their recorded cost.

        Compared against `assumed_cost`, written when the rule was authored,
        rather than a live lookup: the question at publish time is whether the
        author's own cost assumption contradicts their price.
        """
        rows = await self.db.execute(select(PriceRule).where(PriceRule.price_book_id == book.id))
        problems: list[BelowCost] = []
        for rule in rows.scalars():
            if rule.assumed_cost is None:
                continue
            cost = to_decimal(rule.assumed_cost)
            if rule.rate_kind in (RateKind.COST_MARKUP, RateKind.PERCENT):
                continue  # priced off cost; cannot be below it by construction
            if to_decimal(rule.rate) < cost:
                problems.append(BelowCost(str(rule.billable), to_decimal(rule.rate), cost))
        return problems

    async def publish(
        self, book: PriceBook, *, actor_id: uuid.UUID | None, override_reason: str | None
    ) -> PriceBook:
        """Make a draft live, refusing a loss-making book without a signed reason."""
        problems = await self.check_publishable(book)
        if problems and not override_reason:
            raise problems[0]

        book.status = PriceBookStatus.PUBLISHED
        book.published_at = datetime.now(UTC)
        book.published_by_id = actor_id
        book.below_cost_reason = override_reason
        if book.effective_from is None:
            book.effective_from = book.published_at
        await self.db.commit()
        await self.db.refresh(book)
        return book
