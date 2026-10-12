"""Schemas for the platform-administration surface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer

from app.core.times import as_utc
from app.models.impersonation import (
    MIN_REASON_LENGTH,
    ImpersonationEndReason,
    ImpersonationMode,
)


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

    # Messaging, so the platform view is not calls-only.
    messages_30d: int = 0
    messages_delivered_30d: int = 0
    message_revenue_30d_usd: float = 0.0
    delivery_rate: float | None = None


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


class ProviderConnectionRead(BaseModel):
    """A provider as the admin sees it.

    Deliberately has no field that could carry a secret. `secret_hints` holds
    masked tails only -- the last four characters, which an operator compares
    against a vendor dashboard and which identify nothing alone.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    label: str
    kind: str
    environment: str
    is_enabled: bool
    priority: int
    status: str
    status_detail: str | None
    #: {"auth_token": "••••3456"}. Never plaintext.
    secret_hints: dict
    config: dict
    last_checked_at: datetime | None
    last_synced_at: datetime | None
    secrets_rotated_at: datetime | None
    created_at: datetime
    #: Which fields this vendor needs, so the form and the validator agree.
    required_fields: list[str] = []
    optional_fields: list[str] = []
    docs_url: str | None = None


class ProviderWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=48)
    #: Plaintext, inbound only. A blank value leaves that key untouched, so
    #: editing one field in a form does not wipe the others.
    secrets: dict[str, str] = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=120)
    environment: str = Field(default="live", max_length=16)
    is_enabled: bool = True


class ProviderHealth(BaseModel):
    ok: bool
    detail: str
    checked_at: datetime


class PriceRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    billable: str
    region: str | None
    rate_kind: str
    rate: Decimal
    fixed_fee: Decimal | None
    minimum_charge: Decimal | None
    rounding: str
    increment_seconds: int
    assumed_cost: Decimal | None
    notes: str | None

    @field_serializer("rate", "fixed_fee", "minimum_charge", "assumed_cost")
    def _as_string(self, value: Decimal | None) -> str | None:
        # A JSON number is a float. Money is not.
        return None if value is None else str(value)

    @property
    def margin_percent(self) -> Decimal | None:
        if self.assumed_cost is None or self.rate <= 0:
            return None
        return (self.rate - self.assumed_cost) / self.rate * 100


class PriceBookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    version: int
    status: str
    currency: str
    organization_id: uuid.UUID | None
    is_default: bool
    effective_from: datetime | None
    published_at: datetime | None
    below_cost_reason: str | None
    created_at: datetime
    rules: list[PriceRuleRead] = []
    #: Rules priced under their own recorded cost. Empty is the normal state.
    below_cost: list[str] = []


class PriceRuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billable: str
    region: str | None = None
    rate_kind: str = "per_minute"
    rate: Decimal = Field(ge=0)
    minimum_charge: Decimal | None = None
    assumed_cost: Decimal | None = None
    increment_seconds: int = Field(default=60, ge=1, le=600)
    notes: str | None = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Required only when a rule prices below its recorded cost. Selling at a
    #: loss should be a decision someone signed, not an accident.
    override_reason: str | None = Field(default=None, max_length=1000)


class ImpersonationStart(BaseModel):
    """Opening a support session on a customer account."""

    user_id: uuid.UUID
    #: Shown to the customer in their own activity timeline, so it is written
    #: for them rather than for us.
    reason: str = Field(min_length=MIN_REASON_LENGTH, max_length=500)
    #: Defaults closed. Almost every support question is answered by looking,
    #: and a session that can write is one that can break something while
    #: nobody is watching.
    mode: ImpersonationMode = ImpersonationMode.READ_ONLY


class ImpersonationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admin_email: str
    target_email: str
    organization_id: uuid.UUID | None
    organization_name: str
    mode: ImpersonationMode
    reason: str
    created_at: datetime
    expires_at: datetime
    ended_at: datetime | None
    end_reason: ImpersonationEndReason | None
    writes_performed: int
    started_ip: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_active(self) -> bool:
        if self.ended_at is not None:
            return False
        expires = as_utc(self.expires_at)
        return expires is not None and expires > datetime.now(UTC)


class ImpersonationHandoff(BaseModel):
    """What the admin console needs to open the customer app as that customer.

    The code is returned exactly once and is worth a session, so it is never
    logged and never stored anywhere a later request could read it back.
    """

    session: ImpersonationRead
    code: str
    #: Built server-side from the configured app URL rather than assembled in
    #: the browser, so the console cannot be tricked into posting the code to
    #: somebody else's origin.
    handoff_url: str
    expires_in_seconds: int
