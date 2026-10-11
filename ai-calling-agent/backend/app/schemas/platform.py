"""Schemas for the platform-administration surface."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrganizationSummary(BaseModel):
    """One customer, as the platform sees them."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    is_suspended: bool
    suspended_reason: str | None
    credit_balance: float
    credit_overdraft: float
    created_at: datetime

    users: int = 0
    calls: int = 0
    calls_30d: int = 0
    minutes_30d: float = 0.0
    #: What their usage cost us, so margin is visible per customer.
    provider_cost_usd: float = 0.0
    #: Lifetime. Do not compare this against the 30-day cost figures below.
    credits_used: float = 0.0
    #: The same window as provider_cost_usd, so margin is apples-to-apples.
    credits_used_30d: float = 0.0
    last_call_at: datetime | None = None


class PlatformOverview(BaseModel):
    """The numbers that say whether the business is working."""

    organizations: int
    active_organizations: int
    suspended: int
    users: int
    calls_30d: int
    minutes_30d: float
    credits_outstanding: float
    credits_consumed_30d: float
    provider_cost_30d_usd: float
    #: Credit revenue recognised minus what the providers charged us.
    gross_margin_30d_usd: float


class CreditGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credits: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="", max_length=300)


class CreditDeductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credits: float = Field(gt=0, le=10_000_000)
    #: Required: removing someone's credits without a stated reason is the kind
    #: of action that has to be explainable months later.
    note: str = Field(min_length=3, max_length=300)


class SuspendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=300)


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str | None = Field(default=None, pattern="^(trial|starter|growth|scale)$")
    credit_overdraft: float | None = Field(default=None, ge=0, le=100_000)
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=500)
    daily_budget_usd: float | None = Field(default=None, ge=0)
    monthly_budget_usd: float | None = Field(default=None, ge=0)


class PlatformUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    is_platform_admin: bool
    last_login_at: datetime | None
    created_at: datetime
    organization_id: uuid.UUID
    organization_name: str = ""


class CreditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    amount: float
    balance_after: float
    call_id: uuid.UUID | None
    note: str | None
    provider_cost_usd: float | None
    created_at: datetime


class PlatformEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_email: str
    action: str
    organization_id: uuid.UUID | None
    target: str | None
    detail: str | None
    created_at: datetime


class PackageWrite(BaseModel):
    """Creating or editing a package. Money in minor units, tax in bps."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=140, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=2000)
    #: 99900 == Rs999.00. Integer so the arithmetic is exact.
    price_minor: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    #: 1800 == 18%.
    tax_bps: int = Field(default=0, ge=0, le=10_000)
    base_credits: int = Field(ge=0, le=100_000_000)
    bonus_credits: int = Field(default=0, ge=0, le=100_000_000)
    validity_days: int | None = Field(default=None, ge=1, le=3650)
    is_active: bool = True
    is_public: bool = True
    display_order: int = Field(default=0, ge=0, le=999)
    max_per_organization: int | None = Field(default=None, ge=1, le=1000)


class PackageAdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    kind: str
    price_minor: int
    currency: str
    tax_bps: int
    tax_minor: int
    payable_minor: int
    base_credits: int
    bonus_credits: int
    total_credits: int
    validity_days: int | None
    is_active: bool
    is_public: bool
    display_order: int
    max_per_organization: int | None
    created_at: datetime
    #: How many paid orders reference it. A package with sales must never be
    #: deleted, only deactivated.
    orders_paid: int = 0
    revenue_minor: int = 0


class AdminOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    organization_id: uuid.UUID
    organization_name: str = ""
    status: str
    package_name: str
    currency: str
    total_minor: int
    total_credits: int
    provider: str | None
    provider_payment_id: str | None
    paid_at: datetime | None
    credits_allocated_at: datetime | None
    refunded_minor: int
    failure_reason: str | None
    created_at: datetime


class UserProfile(BaseModel):
    """Everything about one customer, in one response.

    Assembled server-side so the admin UI makes one request instead of eight,
    and so every number comes from the same point in time.
    """

    organization: OrganizationSummary
    users: list[PlatformUserRead]

    # Financial
    balance: float
    held: float
    spendable: float
    lifetime_purchased: float
    lifetime_granted: float
    lifetime_consumed: float
    #: Matches provider_cost_30d_usd's window.
    consumed_30d: float
    paid_orders: int
    paid_minor: int
    refunded_minor: int

    # Calling
    calls_total: int
    calls_30d: int
    minutes_30d: float
    failed_30d: int
    by_source: dict[str, int]
    provider_cost_30d_usd: float

    agents: list[dict]
    recent_calls: list[dict]
    recent_credits: list[CreditEntryRead]
    recent_orders: list[AdminOrderRead]
    #: Paid orders whose credits never landed. Should always be empty.
    unallocated_orders: list[AdminOrderRead]
