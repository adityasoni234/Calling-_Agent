from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderStatus(BaseModel):
    selected: str
    configured: bool
    is_mock: bool
    available: list[str]


class SettingsRead(BaseModel):
    organization_name: str
    organization_timezone: str
    daily_budget_usd: float | None = None
    monthly_budget_usd: float | None = None
    max_concurrent_calls: int | None = None
    providers: dict[str, ProviderStatus]
    llm_model: str
    embedding_model: str
    public_base_url: str
    max_global_concurrent_calls: int
    budget: dict[str, Any]
    # True when any live-call provider is still a mock; the dashboard says so
    # loudly rather than letting someone think they are placing real calls.
    using_mocks: bool


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    # 0 means no cap; null clears the override and falls back to the
    # deployment-wide default.
    daily_budget_usd: float | None = Field(default=None, ge=0, le=100000)
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1000000)
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=200)


class PricingRateCreate(BaseModel):
    component: str = Field(max_length=16)
    provider: str = Field(max_length=48)
    model: str | None = Field(default=None, max_length=120)
    unit: str = Field(max_length=32)
    rate: float = Field(ge=0)
    currency: str = Field(default="USD", max_length=8)
    region: str | None = Field(default=None, max_length=16)
    # Mandatory: a rate without a source is how a cost model becomes fiction.
    source_url: str = Field(min_length=5, max_length=600)
    verified_at: datetime


class PricingRateRead(PricingRateCreate):
    id: str
    is_active: bool
