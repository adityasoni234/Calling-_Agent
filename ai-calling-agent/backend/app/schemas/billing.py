"""Customer-facing billing schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PackageRead(BaseModel):
    """A package as shown on the purchase page. Prices come from the server."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    currency: str
    price_minor: int
    tax_minor: int
    payable_minor: int
    base_credits: int
    bonus_credits: int
    total_credits: int
    validity_days: int | None
    display_order: int


class BalanceRead(BaseModel):
    """What the account can actually spend, and why it differs from the total."""

    balance: float
    #: Set aside for calls currently in flight.
    held: float
    #: balance - held. The number every spend decision uses.
    spendable: float
    overdraft: float
    plan: str
    is_suspended: bool
    suspended_reason: str | None
    lifetime_purchased: float
    lifetime_granted: float
    lifetime_consumed: float
    consumed_today: float
    consumed_this_month: float


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The only thing a client may choose. Price and credits come from the
    #: package row, never from the request.
    package_id: uuid.UUID


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    status: str
    package_name: str
    currency: str
    price_minor: int
    tax_minor: int
    total_minor: int
    base_credits: int
    bonus_credits: int
    total_credits: int
    provider: str | None
    provider_order_id: str | None
    provider_payment_id: str | None
    paid_at: datetime | None
    credits_allocated_at: datetime | None
    refunded_minor: int
    failure_reason: str | None
    created_at: datetime


class CheckoutResponse(BaseModel):
    """What the browser needs to open a checkout, plus honesty about setup."""

    order: OrderRead
    #: False when no provider is configured. The UI must say so rather than
    #: opening a checkout that cannot complete.
    provider_configured: bool
    provider: str
    #: Publishable fields only. No secret ever appears here.
    checkout: dict | None = None
    message: str | None = None


class CheckoutConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Whatever the provider's checkout handed back. Verified server-side;
    #: never trusted as proof on its own.
    payload: dict = Field(default_factory=dict)


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    amount: float
    balance_after: float
    call_id: uuid.UUID | None
    order_id: uuid.UUID | None
    note: str | None
    created_at: datetime
