"""Dashboard aggregates and cost reporting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call, CallStatus, CallUsage
from app.models.campaign import Campaign, CampaignStatus
from app.models.lead import Lead, LeadStatus

QUALIFIED = (LeadStatus.QUALIFIED, LeadStatus.CONVERTED)
INTERESTED = (LeadStatus.INTERESTED, LeadStatus.QUALIFIED, LeadStatus.CONVERTED)


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(self, organization_id: uuid.UUID) -> dict[str, Any]:
        now = datetime.now(UTC)
        start_of_day = now - timedelta(days=1)

        totals = (
            await self.db.execute(
                select(
                    func.count(Call.id),
                    func.coalesce(func.sum(Call.cost_usd), 0.0),
                    func.coalesce(func.avg(Call.duration_seconds), 0.0),
                    func.coalesce(
                        func.sum(case((Call.status == CallStatus.COMPLETED, 1), else_=0)), 0
                    ),
                    func.coalesce(func.sum(case((Call.cost_incomplete.is_(True), 1), else_=0)), 0),
                ).where(Call.organization_id == organization_id)
            )
        ).one()

        calls_today = await self.db.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.organization_id == organization_id, Call.created_at >= start_of_day)
        )
        cost_today = await self.db.scalar(
            select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(
                Call.organization_id == organization_id, Call.created_at >= start_of_day
            )
        )
        active_campaigns = await self.db.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(
                Campaign.organization_id == organization_id,
                Campaign.status == CampaignStatus.RUNNING,
            )
        )
        total_leads = await self.db.scalar(
            select(func.count()).select_from(Lead).where(Lead.organization_id == organization_id)
        )
        interested_leads = await self.db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.organization_id == organization_id, Lead.status.in_(INTERESTED))
        )
        qualified_leads = await self.db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.organization_id == organization_id, Lead.status.in_(QUALIFIED))
        )

        total_calls, total_cost, avg_duration, completed, incomplete = totals
        total_calls = int(total_calls or 0)
        total_cost = float(total_cost or 0.0)
        total_minutes = (
            float(
                await self.db.scalar(
                    select(func.coalesce(func.sum(Call.duration_seconds), 0)).where(
                        Call.organization_id == organization_id
                    )
                )
                or 0
            )
            / 60
        )

        return {
            "total_calls": total_calls,
            "calls_today": int(calls_today or 0),
            "completed_calls": int(completed or 0),
            "active_campaigns": int(active_campaigns or 0),
            "total_leads": int(total_leads or 0),
            "interested_leads": int(interested_leads or 0),
            "qualified_leads": int(qualified_leads or 0),
            "average_duration_seconds": round(float(avg_duration or 0.0), 1),
            "total_cost_usd": round(total_cost, 4),
            "cost_today_usd": round(float(cost_today or 0.0), 4),
            "cost_per_call_usd": round(total_cost / total_calls, 4) if total_calls else 0.0,
            "cost_per_minute_usd": round(total_cost / total_minutes, 4) if total_minutes else 0.0,
            "cost_per_qualified_lead_usd": (
                round(total_cost / int(qualified_leads), 4) if qualified_leads else 0.0
            ),
            # The number of calls whose cost is a floor, not a real total,
            # because a rate was missing. Never hidden.
            "calls_with_incomplete_cost": int(incomplete or 0),
        }

    async def calls_per_day(
        self, organization_id: uuid.UUID, days: int = 14
    ) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await self.db.execute(
            select(
                func.date(Call.created_at).label("day"),
                func.count(Call.id),
                func.coalesce(func.sum(Call.cost_usd), 0.0),
                func.coalesce(func.sum(case((Call.status == CallStatus.COMPLETED, 1), else_=0)), 0),
            )
            .where(Call.organization_id == organization_id, Call.created_at >= since)
            .group_by(func.date(Call.created_at))
            .order_by(func.date(Call.created_at))
        )
        return [
            {
                "date": str(day),
                "calls": int(count),
                "cost_usd": round(float(cost), 4),
                "completed": int(completed),
            }
            for day, count, cost, completed in rows
        ]

    async def outcome_breakdown(self, organization_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(Call.status, func.count(Call.id))
            .where(Call.organization_id == organization_id)
            .group_by(Call.status)
        )
        return [{"status": str(status), "count": int(count)} for status, count in rows]

    async def lead_funnel(self, organization_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(Lead.status, func.count(Lead.id))
            .where(Lead.organization_id == organization_id)
            .group_by(Lead.status)
        )
        return [{"status": str(status), "count": int(count)} for status, count in rows]

    async def cost_breakdown(self, organization_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(
                CallUsage.component,
                func.coalesce(func.sum(CallUsage.cost_usd), 0.0),
                func.coalesce(func.sum(CallUsage.quantity), 0.0),
                func.sum(case((CallUsage.priced.is_(False), 1), else_=0)),
            )
            .where(CallUsage.organization_id == organization_id)
            .group_by(CallUsage.component)
        )
        return [
            {
                "component": str(component),
                "cost_usd": round(float(cost), 4),
                "quantity": round(float(quantity), 2),
                "unpriced_lines": int(unpriced or 0),
            }
            for component, cost, quantity, unpriced in rows
        ]

    async def campaign_performance(self, organization_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(
                Campaign.id,
                Campaign.name,
                Campaign.status,
                func.count(Call.id),
                func.coalesce(func.sum(Call.cost_usd), 0.0),
                func.coalesce(func.sum(case((Call.status == CallStatus.COMPLETED, 1), else_=0)), 0),
            )
            .outerjoin(Call, Call.campaign_id == Campaign.id)
            .where(Campaign.organization_id == organization_id)
            .group_by(Campaign.id, Campaign.name, Campaign.status)
            .order_by(Campaign.created_at.desc())
            .limit(20)
        )
        return [
            {
                "campaign_id": str(campaign_id),
                "name": name,
                "status": str(status),
                "calls": int(calls),
                "completed": int(completed),
                "cost_usd": round(float(cost), 4),
                "cost_per_call_usd": round(float(cost) / int(calls), 4) if calls else 0.0,
            }
            for campaign_id, name, status, calls, cost, completed in rows
        ]
