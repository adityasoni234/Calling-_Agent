"""Customer billing: balance, packages, checkout and history.

Everything here is scoped to the caller's own organization. There is no path
by which a request can name another organization, and no parameter through
which a price or a credit quantity can be supplied -- both come from the
database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, requires
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Capability
from app.models.billing import CreditEntry, CreditEntryKind
from app.models.organization import Organization
from app.models.package import Order, OrderStatus
from app.models.user import User
from app.schemas.billing import (
    BalanceRead,
    CheckoutConfirm,
    CheckoutResponse,
    LedgerEntryRead,
    OrderCreate,
    OrderRead,
    PackageRead,
)
from app.schemas.common import Page
from app.services.billing_service import BillingService, spend_total
from app.services.order_service import OrderService
from app.services.payments.base import PaymentNotConfigured
from app.services.payments.razorpay import get_payment_provider

log = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _package_read(package) -> PackageRead:  # noqa: ANN001 - SQLAlchemy model
    return PackageRead(
        **{
            field: getattr(package, field)
            for field in PackageRead.model_fields
            if field not in {"tax_minor", "payable_minor", "total_credits"}
        },
        tax_minor=package.tax_minor,
        payable_minor=package.payable_minor,
        total_credits=package.total_credits,
    )


@router.get("/packages", response_model=list[PackageRead], summary="Packages you can buy")
async def packages(db: DbSession, user: CurrentUser) -> list[PackageRead]:
    return [_package_read(package) for package in await OrderService(db).purchasable()]


@router.get("/credits/balance", response_model=BalanceRead, summary="Your credit balance")
async def balance(db: DbSession, user: CurrentUser) -> BalanceRead:
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    billing = BillingService(db)

    async def _sum(kinds: list[CreditEntryKind], since: datetime | None = None) -> float:
        statement = select(func.coalesce(func.sum(CreditEntry.amount), 0.0)).where(
            CreditEntry.organization_id == organization.id, CreditEntry.kind.in_(kinds)
        )
        if since is not None:
            statement = statement.where(CreditEntry.created_at >= since)
        return float(await db.scalar(statement) or 0.0)

    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = midnight.replace(day=1)

    return BalanceRead(
        balance=round(organization.credit_balance, 2),
        held=await billing.held_credits(organization.id),
        spendable=await billing.spendable(organization.id),
        overdraft=organization.credit_overdraft,
        plan=organization.plan,
        is_suspended=organization.is_suspended,
        suspended_reason=organization.suspended_reason,
        lifetime_purchased=round(await _sum([CreditEntryKind.PURCHASE]), 2),
        lifetime_granted=round(await _sum([CreditEntryKind.GRANT]), 2),
        # Usage entries are negative; report consumption as a positive number.
        lifetime_consumed=spend_total(await _sum([CreditEntryKind.USAGE])),
        consumed_today=spend_total(await _sum([CreditEntryKind.USAGE], midnight)),
        consumed_this_month=spend_total(await _sum([CreditEntryKind.USAGE], month_start)),
    )


@router.get("/credits/ledger", response_model=Page[LedgerEntryRead], summary="Credit history")
async def ledger(
    db: DbSession, user: CurrentUser, page: PageParam = 1, page_size: PageSizeParam = 25
) -> Page[LedgerEntryRead]:
    statement = (
        select(CreditEntry)
        .where(CreditEntry.organization_id == user.organization_id)
        .order_by(CreditEntry.created_at.desc())
    )
    return await paginate(db, statement, page=page, page_size=page_size, schema=LedgerEntryRead)


@router.get("/orders", response_model=Page[OrderRead], summary="Your payment history")
async def orders(
    db: DbSession, user: CurrentUser, page: PageParam = 1, page_size: PageSizeParam = 25
) -> Page[OrderRead]:
    statement = (
        select(Order)
        .where(Order.organization_id == user.organization_id)
        .order_by(Order.created_at.desc())
    )
    return await paginate(db, statement, page=page, page_size=page_size, schema=OrderRead)


@router.get("/orders/{order_id}", response_model=OrderRead, summary="One order")
async def order_detail(order_id: uuid.UUID, db: DbSession, user: CurrentUser) -> OrderRead:
    order = await db.get(Order, order_id)
    # Ownership, not just existence: changing the id in the URL must not work.
    if order is None or order.organization_id != user.organization_id:
        raise NotFoundError("Order not found")
    return OrderRead.model_validate(order)


@router.post(
    "/orders",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a purchase",
)
async def create_order(
    payload: OrderCreate,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.BUY_CREDITS))],
) -> CheckoutResponse:
    """Create the order first, then ask the provider.

    The order exists even when no provider is configured, so the attempt is
    recorded and the customer is told plainly why they cannot pay yet.
    """
    service = OrderService(db)
    order = await service.create_order(
        organization_id=user.organization_id, package_id=payload.package_id, user_id=user.id
    )

    provider = get_payment_provider()
    if not provider.configured:
        return CheckoutResponse(
            order=OrderRead.model_validate(order),
            provider_configured=False,
            provider=provider.name,
            message=(
                "Online payment is not set up yet. Your order has been recorded — "
                "contact us to complete it, and the credits will be added to this account."
            ),
        )

    try:
        created = await provider.create_order(
            amount_minor=order.total_minor,
            currency=order.currency,
            reference=order.reference,
            notes={"package": order.package_name, "reference": order.reference},
        )
    except PaymentNotConfigured as exc:
        return CheckoutResponse(
            order=OrderRead.model_validate(order),
            provider_configured=False,
            provider=provider.name,
            message=str(exc),
        )

    order.provider = provider.name
    order.provider_order_id = created.provider_order_id
    order.status = OrderStatus.PENDING
    await db.commit()
    await db.refresh(order)

    return CheckoutResponse(
        order=OrderRead.model_validate(order),
        provider_configured=True,
        provider=provider.name,
        checkout=created.checkout,
    )


@router.post("/orders/{order_id}/confirm", response_model=OrderRead, summary="Confirm a payment")
async def confirm_order(
    order_id: uuid.UUID,
    payload: CheckoutConfirm,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.BUY_CREDITS))],
) -> OrderRead:
    """Verify a checkout handback and allocate credits.

    Two independent checks before any credit is granted: the handback's
    signature must verify, and the provider must confirm the payment was
    captured. The browser's word alone is never enough.
    """
    order = await db.get(Order, order_id)
    if order is None or order.organization_id != user.organization_id:
        raise NotFoundError("Order not found")
    if order.credits_allocated_at is not None:
        return OrderRead.model_validate(order)  # already done; refreshing is harmless

    provider = get_payment_provider()
    if not provider.configured:
        raise AppError("No payment provider is configured", code="provider_unconfigured")

    try:
        provider.verify_checkout(payload.payload)
    except ValueError as exc:
        await OrderService(db).mark_failed(order, f"Signature check failed: {exc}")
        raise AppError("That payment could not be verified", code="verification_failed") from exc

    payment_id = str(payload.payload.get("razorpay_payment_id", ""))
    verified = await provider.fetch_payment(payment_id)
    if verified.status != "paid":
        await OrderService(db).mark_failed(order, f"Provider reports {verified.status}")
        raise AppError(
            f"The payment is {verified.status}, not completed", code="payment_not_captured"
        )

    order = await OrderService(db).mark_paid(
        order,
        provider=provider.name,
        provider_payment_id=verified.provider_payment_id,
        amount_minor=verified.amount_minor,
        currency=verified.currency,
    )
    return OrderRead.model_validate(order)


@router.get("/usage", summary="What your credits were spent on")
async def usage(db: DbSession, user: CurrentUser, days: int = 30) -> dict:
    """Consumption by day, so a customer can see where the money went."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            func.date(CreditEntry.created_at).label("day"),
            func.coalesce(func.sum(-CreditEntry.amount), 0.0).label("credits"),
            func.count().label("calls"),
        )
        .where(
            CreditEntry.organization_id == user.organization_id,
            CreditEntry.kind == CreditEntryKind.USAGE,
            CreditEntry.created_at >= since,
        )
        .group_by(func.date(CreditEntry.created_at))
        .order_by(func.date(CreditEntry.created_at))
    )
    daily = [
        {"day": str(day), "credits": round(float(credits), 2), "calls": int(calls)}
        for day, credits, calls in rows.all()
    ]
    return {
        "days": days,
        "daily": daily,
        "total_credits": round(sum(item["credits"] for item in daily), 2),
        "total_calls": sum(item["calls"] for item in daily),
    }
