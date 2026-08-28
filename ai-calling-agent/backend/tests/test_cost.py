"""Cost engine: the rule is that an unverified rate is never guessed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.call import Call, CallStatus, CallUsage, UsageComponent
from app.models.pricing import PricingRate
from app.models.user import User
from app.services.base import UsageRecord
from app.services.cost_service import CostService


async def _call(db, organization_id, agent_id) -> Call:
    call = Call(
        organization_id=organization_id,
        agent_id=agent_id,
        provider="mock",
        to_number="+919876543210",
        status=CallStatus.COMPLETED,
        duration_seconds=120,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


@pytest.fixture
async def context(db_session, agent: dict, auth_headers: dict[str, str]):
    import uuid

    user = (
        await db_session.execute(select(User).where(User.email == "owner@example.com"))
    ).unique().scalar_one()
    call = await _call(db_session, user.organization_id, uuid.UUID(agent["id"]))
    return db_session, user, call


async def test_usage_without_a_verified_rate_is_recorded_but_not_priced(context) -> None:
    db, _user, call = context
    total, incomplete = await CostService(db).record_usage(
        call=call,
        records=[UsageRecord(UsageComponent.TELEPHONY, "mock", "minute", 2.0, None)],
    )

    assert total == 0.0
    assert incomplete is True
    # The call is flagged rather than shown as costing zero.
    assert call.cost_incomplete is True
    assert call.cost_usd == 0.0

    lines = (await db.execute(select(CallUsage).where(CallUsage.call_id == call.id))).scalars().all()
    assert len(lines) == 1
    assert lines[0].priced is False
    assert lines[0].quantity == 2.0


async def test_a_verified_rate_prices_the_line(context) -> None:
    db, user, call = context
    db.add(
        PricingRate(
            organization_id=user.organization_id,
            component="telephony",
            provider="mock",
            unit="minute",
            rate=0.02,
            source_url="https://example.com/pricing",
            verified_at=datetime.now(UTC),
        )
    )
    await db.commit()

    total, incomplete = await CostService(db).record_usage(
        call=call,
        records=[UsageRecord(UsageComponent.TELEPHONY, "mock", "minute", 2.0, None)],
    )

    assert total == pytest.approx(0.04)
    assert incomplete is False
    assert call.cost_usd == pytest.approx(0.04)
    assert call.cost_incomplete is False


async def test_per_thousand_units_are_divided_correctly(context) -> None:
    db, user, call = context
    db.add(
        PricingRate(
            organization_id=user.organization_id,
            component="llm",
            provider="mock",
            model="mock",
            unit="token_in_1k",
            rate=1.0,
            source_url="https://example.com/llm",
            verified_at=datetime.now(UTC),
        )
    )
    await db.commit()

    total, _ = await CostService(db).record_usage(
        call=call,
        records=[UsageRecord(UsageComponent.LLM, "mock", "token_in", 2500.0, "mock")],
    )
    assert total == pytest.approx(2.5)


async def test_mixed_usage_keeps_the_incomplete_flag(context) -> None:
    db, user, call = context
    db.add(
        PricingRate(
            organization_id=user.organization_id,
            component="telephony",
            provider="mock",
            unit="minute",
            rate=0.02,
            source_url="https://example.com/pricing",
            verified_at=datetime.now(UTC),
        )
    )
    await db.commit()

    total, incomplete = await CostService(db).record_usage(
        call=call,
        records=[
            UsageRecord(UsageComponent.TELEPHONY, "mock", "minute", 1.0, None),
            UsageRecord(UsageComponent.TTS, "mock", "character", 500.0, None),
        ],
    )

    # A partial total must never be presented as complete.
    assert total == pytest.approx(0.02)
    assert incomplete is True
    assert call.cost_incomplete is True


async def test_budget_blocks_a_new_call(context, monkeypatch) -> None:
    db, user, call = context
    call.cost_usd = 5.0
    await db.commit()

    from app.core.config import settings

    monkeypatch.setattr(settings, "daily_budget_usd", 1.0)
    allowed, reason = await CostService(db).can_start_call(user.organization_id)
    assert allowed is False
    assert "Daily budget" in (reason or "")

    monkeypatch.setattr(settings, "daily_budget_usd", 100.0)
    allowed, _ = await CostService(db).can_start_call(user.organization_id)
    assert allowed is True
