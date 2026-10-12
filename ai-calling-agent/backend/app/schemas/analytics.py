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

    # Messaging. A dashboard that counts calls and ignores messages tells a
    # customer who mostly texts that nothing is happening on their account.
    messages_sent: int = 0
    messages_today: int = 0
    messages_delivered: int = 0
    messages_failed: int = 0
    #: Replies waiting. The one messaging number that needs an action.
    unread_replies: int = 0
    #: Of attempted sends; suppressed ones are excluded rather than counted
    #: as failures, or a healthy opt-out list looks like a broken sender.
    delivery_rate: float | None = None
    message_cost_usd: float = 0.0
    active_message_campaigns: int = 0

    # Email and lead sources. A channel that is live but absent from the
    # dashboard is a channel customers assume is broken.
    emails_sent: int = 0
    emails_delivered: int = 0
    emails_bounced: int = 0
    email_spend_usd: float = 0.0
    email_blocked: int = 0
    #: Leads arriving from connected Meta lead forms.
    meta_leads: int = 0
    leads_by_source: dict[str, int] = {}


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
