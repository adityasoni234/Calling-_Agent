"""Cost engine.

The rule this file enforces: a usage line with no verified rate is recorded but
never priced, and the call is flagged `cost_incomplete`. A confident wrong
number is worse than a visible gap, because voice-AI margins are decided in the
third decimal place.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call import Call, CallUsage
from app.models.pricing import PricingRate
from app.services.base import UsageRecord

log = get_logger(__name__)

# Rates are quoted per unit, per 1k tokens, or per 1k characters depending on
# the vendor. The unit string on the rate row decides the divisor.
UNIT_DIVISOR = {
    "minute": 1.0,
    "second": 1.0,
    "character": 1.0,
    "character_1k": 1000.0,
    "token_in": 1.0,
    "token_out": 1.0,
    "token_1k": 1000.0,
    "token_in_1k": 1000.0,
    "token_out_1k": 1000.0,
    "token_cache_read_1k": 1000.0,
    "token_cache_write_1k": 1000.0,
    "call": 1.0,
}


class CostService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _find_rate(
        self, organization_id: uuid.UUID, record: UsageRecord
    ) -> PricingRate | None:
        """Most specific active rate wins: org-scoped and model-scoped first."""
        candidates = [record.unit, f"{record.unit}_1k"]
        query = (
            select(PricingRate)
            .where(
                PricingRate.is_active.is_(True),
                PricingRate.component == record.component.value,
                PricingRate.provider == record.provider,
                PricingRate.unit.in_(candidates),
                or_(
                    PricingRate.organization_id == organization_id,
                    PricingRate.organization_id.is_(None),
                ),
                or_(
                    PricingRate.model.is_(None),
                    PricingRate.model == (record.model or ""),
                ),
            )
            .order_by(
                PricingRate.organization_id.is_(None),  # org-specific first
                PricingRate.model.is_(None),  # model-specific first
                PricingRate.verified_at.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def record_usage(
        self, *, call: Call, records: Iterable[UsageRecord], commit: bool = True
    ) -> tuple[float, bool]:
        """Persist usage lines, pricing the ones we have verified rates for."""
        total = 0.0
        incomplete = False

        for record in records:
            if record.quantity <= 0:
                continue
            rate = await self._find_rate(call.organization_id, record)
            cost: float | None = None
            if rate is not None:
                divisor = UNIT_DIVISOR.get(rate.unit, 1.0)
                cost = (record.quantity / divisor) * rate.rate
                total += cost
            else:
                incomplete = True

            self.db.add(
                CallUsage(
                    call_id=call.id,
                    organization_id=call.organization_id,
                    component=record.component,
                    provider=record.provider,
                    model=record.model,
                    unit=record.unit,
                    quantity=record.quantity,
                    cost_usd=cost,
                    priced=cost is not None,
                )
            )

        call.cost_usd = round((call.cost_usd or 0.0) + total, 6)
        call.cost_incomplete = call.cost_incomplete or incomplete
        if commit:
            await self.db.commit()

        if incomplete:
            log.info("cost.incomplete", call_id=str(call.id), reason="missing verified rate")
        return total, incomplete

    # --- budgets -------------------------------------------------------

    async def spend_since(self, organization_id: uuid.UUID, since: datetime) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(
                and_(Call.organization_id == organization_id, Call.created_at >= since)
            )
        )
        return float(result.scalar_one() or 0.0)

    async def budget_state(self, organization_id: uuid.UUID) -> dict[str, float | bool]:
        now = datetime.now(UTC)
        daily = await self.spend_since(organization_id, now - timedelta(days=1))
        monthly = await self.spend_since(organization_id, now - timedelta(days=30))
        daily_limit = settings.daily_budget_usd
        monthly_limit = settings.monthly_budget_usd
        return {
            "daily_spend": round(daily, 4),
            "monthly_spend": round(monthly, 4),
            "daily_limit": daily_limit,
            "monthly_limit": monthly_limit,
            "daily_exceeded": bool(daily_limit and daily >= daily_limit),
            "monthly_exceeded": bool(monthly_limit and monthly >= monthly_limit),
        }

    async def can_start_call(self, organization_id: uuid.UUID) -> tuple[bool, str | None]:
        """Checked before origination -- an in-flight call cannot be un-billed."""
        state = await self.budget_state(organization_id)
        if state["daily_exceeded"]:
            return False, "Daily budget limit reached"
        if state["monthly_exceeded"]:
            return False, "Monthly budget limit reached"
        return True, None
