from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.analytics import (
    AnalyticsBundle,
    CampaignPerformance,
    CostLine,
    NamedCount,
    Overview,
    TimeSeriesPoint,
)
from app.services.analytics_service import AnalyticsService
from app.services.cost_service import CostService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=Overview, summary="Headline metrics")
async def overview(db: DbSession, user: CurrentUser) -> Overview:
    return Overview(**await AnalyticsService(db).overview(user.organization_id))


@router.get(
    "", response_model=AnalyticsBundle, summary="Everything the dashboard needs, in one call"
)
async def bundle(
    db: DbSession, user: CurrentUser, days: int = Query(default=14, ge=1, le=90)
) -> AnalyticsBundle:
    """One round trip instead of six -- the dashboard renders as a unit."""
    service = AnalyticsService(db)
    organization_id = user.organization_id
    return AnalyticsBundle(
        overview=Overview(**await service.overview(organization_id)),
        calls_per_day=[
            TimeSeriesPoint(**point) for point in await service.calls_per_day(organization_id, days)
        ],
        outcomes=[NamedCount(**row) for row in await service.outcome_breakdown(organization_id)],
        lead_funnel=[NamedCount(**row) for row in await service.lead_funnel(organization_id)],
        cost_breakdown=[CostLine(**row) for row in await service.cost_breakdown(organization_id)],
        campaigns=[
            CampaignPerformance(**row)
            for row in await service.campaign_performance(organization_id)
        ],
        budget=await CostService(db).budget_state(organization_id),
    )
