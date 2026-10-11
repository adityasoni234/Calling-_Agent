"""The pricing engine: what a customer is charged, and why.

These are the money paths, so they assert on exact Decimals rather than
approximations. A test that tolerates a cent of drift cannot catch the bug
this engine exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.money import billable_minutes, margin_percent, quantize_money
from app.models.organization import Organization
from app.models.price_book import (
    Billable,
    PriceBook,
    PriceBookStatus,
    PriceOverride,
    PriceRule,
    RateKind,
    Rounding,
)
from app.models.user import User
from app.services.pricing_engine import BelowCost, PricingEngine
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _book(
    db_session,
    *,
    rate: str = "0.13",
    billable: Billable = Billable.VOICE_OUTBOUND,
    kind: RateKind = RateKind.PER_MINUTE,
    assumed_cost: str | None = None,
    published: bool = True,
    organization_id=None,
    **rule_kwargs,
) -> PriceBook:
    book = PriceBook(
        slug=f"book-{uuid.uuid4().hex[:8]}",
        name="Standard",
        version=1,
        status=PriceBookStatus.PUBLISHED if published else PriceBookStatus.DRAFT,
        organization_id=organization_id,
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        PriceRule(
            price_book_id=book.id,
            billable=billable,
            rate_kind=kind,
            rate=Decimal(rate),
            assumed_cost=Decimal(assumed_cost) if assumed_cost else None,
            **rule_kwargs,
        )
    )
    await db_session.commit()
    return book


# --- rounding ---------------------------------------------------------


def test_a_partial_minute_bills_as_a_whole_one() -> None:
    """Carriers round up, so billing per second while paying per minute loses money."""
    assert billable_minutes(1) == Decimal("1")
    assert billable_minutes(17) == Decimal("1")
    assert billable_minutes(60) == Decimal("1")
    assert billable_minutes(61) == Decimal("2")
    assert billable_minutes(0) == Decimal("0")
    assert billable_minutes(None) == Decimal("0")


def test_margin_on_a_free_call_is_unknown_not_zero() -> None:
    """A percentage of nothing is not a fact, and must not print as one."""
    assert margin_percent(Decimal("0"), Decimal("5")) is None
    assert margin_percent(Decimal("0.13"), Decimal("0.0555")) == Decimal("57.31")


# --- quoting ----------------------------------------------------------


async def test_a_seventeen_second_call_is_charged_a_full_minute(db_session) -> None:
    await _book(db_session, rate="0.13")
    quote = await PricingEngine(db_session).quote(
        billable=Billable.VOICE_OUTBOUND, seconds=17, provider_cost=Decimal("0.0555")
    )
    assert quote.charge == Decimal("0.13")
    assert quote.billed_quantity == Decimal("1")
    assert quote.gross_profit == Decimal("0.0745")


async def test_per_second_rounding_charges_only_what_was_used(db_session) -> None:
    await _book(db_session, rate="0.13", rounding=Rounding.PER_SECOND)
    quote = await PricingEngine(db_session).quote(
        billable=Billable.VOICE_OUTBOUND, seconds=30, provider_cost=Decimal("0.0555")
    )
    # 30s of a $0.13 minute is exactly 6.5 cents, and it stays 6.5 cents:
    # rounding per charge is what the micro precision exists to avoid.
    assert quote.charge == Decimal("0.065000")


async def test_an_unpriced_item_is_never_silently_free(db_session) -> None:
    """No rule must mean "we cannot bill this yet", not "this costs nothing"."""
    quote = await PricingEngine(db_session).quote(
        billable=Billable.WHATSAPP_OUTBOUND, units=Decimal("100")
    )
    assert quote.charge == Decimal("0")
    assert quote.source == "unpriced"
    assert quote.cost_incomplete is True
    assert quote.gross_margin_percent is None


async def test_a_missing_cost_component_blocks_any_margin_claim(db_session) -> None:
    """The directive's rule: show "Cost incomplete", never a confident number."""
    await _book(db_session, rate="0.13")
    quote = await PricingEngine(db_session).quote(
        billable=Billable.VOICE_OUTBOUND,
        seconds=60,
        provider_cost=Decimal("0.0555"),
        cost_incomplete=True,
    )
    assert quote.charge == Decimal("0.13")
    assert quote.gross_profit is None
    assert quote.gross_margin_percent is None
    assert quote.as_dict()["cost_incomplete"] is True


async def test_a_minimum_charge_covers_a_call_that_barely_connected(db_session) -> None:
    await _book(db_session, rate="0.13", minimum_charge=Decimal("0.05"))
    engine = PricingEngine(db_session)
    assert (await engine.quote(billable=Billable.VOICE_OUTBOUND, seconds=0)).charge == Decimal(
        "0"
    )  # never answered: no minimum
    assert (await engine.quote(billable=Billable.VOICE_OUTBOUND, seconds=1)).charge == Decimal(
        "0.13"
    )


async def test_cost_markup_follows_the_carrier_down(db_session) -> None:
    """Switching to a cheaper carrier must lower the price, not the margin."""
    await _book(db_session, rate="3.0", kind=RateKind.COST_MARKUP)
    engine = PricingEngine(db_session)
    dear = await engine.quote(
        billable=Billable.VOICE_OUTBOUND, seconds=60, provider_cost=Decimal("0.0744")
    )
    cheap = await engine.quote(
        billable=Billable.VOICE_OUTBOUND, seconds=60, provider_cost=Decimal("0.0114")
    )
    assert cheap.charge < dear.charge
    assert cheap.gross_margin_percent == dear.gross_margin_percent


async def test_tiers_are_graduated_so_the_bill_never_falls_as_usage_rises(
    db_session,
) -> None:
    await _book(
        db_session,
        rate="0.01",
        billable=Billable.SMS_OUTBOUND,
        kind=RateKind.TIERED,
        tiers=[{"up_to": "1000", "rate": "0.01"}, {"up_to": None, "rate": "0.005"}],
    )
    engine = PricingEngine(db_session)
    at_cap = await engine.quote(billable=Billable.SMS_OUTBOUND, units=Decimal("1000"))
    over = await engine.quote(billable=Billable.SMS_OUTBOUND, units=Decimal("2000"))
    assert at_cap.charge == Decimal("10.00")
    assert over.charge == Decimal("15.00")  # 1000*0.01 + 1000*0.005
    assert over.charge > at_cap.charge


# --- resolution order -------------------------------------------------


async def test_a_negotiated_override_beats_the_platform_price(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _book(db_session, rate="0.13")
    db_session.add(
        PriceOverride(
            organization_id=org.id,
            billable=Billable.VOICE_OUTBOUND,
            rate_kind=RateKind.PER_MINUTE,
            rate=Decimal("0.09"),
            reason="Annual commitment, signed 2026-09",
        )
    )
    await db_session.commit()

    engine = PricingEngine(db_session)
    theirs = await engine.quote(
        billable=Billable.VOICE_OUTBOUND, organization_id=org.id, seconds=60
    )
    everyone = await engine.quote(billable=Billable.VOICE_OUTBOUND, seconds=60)
    assert theirs.charge == Decimal("0.09")
    assert theirs.source == "override"
    assert everyone.charge == Decimal("0.13")


async def test_an_expired_override_falls_back_to_the_list_price(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _book(db_session, rate="0.13")
    db_session.add(
        PriceOverride(
            organization_id=org.id,
            billable=Billable.VOICE_OUTBOUND,
            rate_kind=RateKind.PER_MINUTE,
            rate=Decimal("0.09"),
            reason="Trial discount",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db_session.commit()
    quote = await PricingEngine(db_session).quote(
        billable=Billable.VOICE_OUTBOUND, organization_id=org.id, seconds=60
    )
    assert quote.charge == Decimal("0.13")


async def test_a_draft_price_book_never_charges_anyone(db_session) -> None:
    await _book(db_session, rate="0.13", published=False)
    quote = await PricingEngine(db_session).quote(billable=Billable.VOICE_OUTBOUND, seconds=60)
    assert quote.source == "unpriced"


# --- the publish guard ------------------------------------------------


async def test_publishing_below_cost_is_refused_without_a_signed_reason(
    db_session,
) -> None:
    """The spec's own $0.10 enterprise floor is below measured cost.

    With AI included a connected minute costs about $0.1147, so the floor
    sells at a loss. The guard exists so that is a decision someone recorded,
    not something discovered in a monthly report.
    """
    book = await _book(db_session, rate="0.10", assumed_cost="0.1147", published=False)
    engine = PricingEngine(db_session)

    problems = await engine.check_publishable(book)
    assert len(problems) == 1
    assert problems[0].price == Decimal("0.10")
    assert problems[0].cost == Decimal("0.1147")

    book_id = book.id  # read before the rollback expires the instance
    with pytest.raises(BelowCost):
        await engine.publish(book, actor_id=None, override_reason=None)
    await db_session.rollback()
    assert (await db_session.get(PriceBook, book_id)).status == PriceBookStatus.DRAFT


async def test_a_recorded_reason_lets_a_loss_leader_through(db_session) -> None:
    book = await _book(db_session, rate="0.10", assumed_cost="0.1147", published=False)
    published = await PricingEngine(db_session).publish(
        book, actor_id=None, override_reason="Land-and-expand: approved by founder"
    )
    assert published.status == PriceBookStatus.PUBLISHED
    assert "founder" in published.below_cost_reason
    assert published.effective_from is not None


async def test_the_standard_tier_publishes_cleanly(db_session) -> None:
    book = await _book(db_session, rate="0.13", assumed_cost="0.1147", published=False)
    engine = PricingEngine(db_session)
    assert await engine.check_publishable(book) == []
    assert (
        await engine.publish(book, actor_id=None, override_reason=None)
    ).status == PriceBookStatus.PUBLISHED


async def test_a_cost_markup_rule_can_never_be_below_cost(db_session) -> None:
    """Priced off measured cost, so the guard has nothing to catch."""
    book = await _book(
        db_session,
        rate="3.0",
        kind=RateKind.COST_MARKUP,
        assumed_cost="0.1147",
        published=False,
    )
    assert await PricingEngine(db_session).check_publishable(book) == []


# --- decimal safety ---------------------------------------------------


def test_money_never_goes_through_a_float() -> None:
    """0.1 + 0.2 == 0.30000000000000004 is why this module exists."""
    assert quantize_money(0.1) + quantize_money(0.2) == Decimal("0.30")
    assert quantize_money("0.005") == Decimal("0.01")  # half-up, not bankers'
