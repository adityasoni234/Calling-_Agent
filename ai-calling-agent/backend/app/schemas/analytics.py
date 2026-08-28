from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Overview(BaseModel):
    total_calls: int
    calls_today: int
    completed_calls: int
    active_campaigns: int
    total_leads: int
    interested_leads: int
    qualified_leads: int
    average_duration_seconds: float
    total_cost_usd: float
    cost_today_usd: float
    cost_per_call_usd: float
    cost_per_minute_usd: float
    cost_per_qualified_lead_usd: float
    calls_with_incomplete_cost: int


class TimeSeriesPoint(BaseModel):
    date: str
    calls: int
    cost_usd: float
    completed: int


class NamedCount(BaseModel):
    status: str
    count: int


class CostLine(BaseModel):
    component: str
    cost_usd: float
    quantity: float
    unpriced_lines: int


class CampaignPerformance(BaseModel):
    campaign_id: str
    name: str
    status: str
    calls: int
    completed: int
    cost_usd: float
    cost_per_call_usd: float


class AnalyticsBundle(BaseModel):
    overview: Overview
    calls_per_day: list[TimeSeriesPoint]
    outcomes: list[NamedCount]
    lead_funnel: list[NamedCount]
    cost_breakdown: list[CostLine]
    campaigns: list[CampaignPerformance]
    budget: dict[str, Any]
