"""Buying credits: orders, and the one place credits are granted for a payment.

Two rules shape everything here.

The price is decided on the server. A client that can name its own price can
buy ten thousand credits for one rupee, so the package is loaded from the
database and the total recomputed, whatever the request said.

Credits are granted exactly once per order. Payment providers retry webhooks,
users refresh the success page, and workers restart -- all three arrive as a
second confirmation for a payment that already happened.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.models.billing import CreditEntryKind
from app.models.package import CreditPackage, Order, OrderStatus
from app.services.billing_service import BillingService

log = get_logger(__name__)


def _reference() -> str:
    """Short, unambiguous, and safe to read down a phone line."""
    alphabet = "ACDEFGHJKLMNPQRSTUVWXYZ2345679"  # no I/O/0/1/B/8
    return "SV-" + "".join(secrets.choice(alphabet) for _ in range(8))


class OrderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def purchasable(self, *, include_hidden: bool = False) -> list[CreditPackage]:
        """Packages a customer may buy right now."""
        now = datetime.now(UTC)
        statement = select(CreditPackage).where(CreditPackage.is_active.is_(True))
        if not include_hidden:
            statement = statement.where(CreditPackage.is_public.is_(True))
        rows = await self.db.execute(
            statement.order_by(CreditPackage.display_order, CreditPackage.price_minor)
        )
        return [
            package
            for package in rows.scalars()
            if (package.available_from is None or package.available_from <= now)
            and (package.available_until is None or package.available_until >= now)
        ]

    async def create_order(
        self,
        *,
        organization_id: uuid.UUID,
        package_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> Order:
        """Open a purchase, snapshotting the terms it was bought under."""
        package = await self.db.get(CreditPackage, package_id)
        if package is None or not package.is_active:
            raise NotFoundError("That package is not available")

        now = datetime.now(UTC)
        if package.available_from and package.available_from > now:
            raise AppError("That package is not on sale yet", code="package_not_yet_available")
        if package.available_until and package.available_until < now:
            raise AppError("That package is no longer on sale", code="package_expired")

        if package.max_per_organization is not None:
            bought = await self.db.scalar(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.organization_id == organization_id,
                    Order.package_id == package.id,
                    Order.status == OrderStatus.PAID,
                )
            )
            if int(bought or 0) >= package.max_per_organization:
                raise AppError(
                    f"This package is limited to {package.max_per_organization} per account",
                    code="package_limit_reached",
                )

        order = Order(
            organization_id=organization_id,
            created_by_user_id=user_id,
            package_id=package.id,
            reference=_reference(),
            status=OrderStatus.CREATED,
            # The snapshot. Everything below is computed here, never sent by
            # the client, and never re-read from the package afterwards.
            package_name=package.name,
            price_minor=package.price_minor,
            tax_minor=package.tax_minor,
            total_minor=package.payable_minor,
            currency=package.currency,
            base_credits=package.base_credits,
            bonus_credits=package.bonus_credits,
            total_credits=package.total_credits,
            validity_days=package.validity_days,
        )
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        log.info(
            "order.created",
            reference=order.reference,
            total_minor=order.total_minor,
            credits=order.total_credits,
        )
        return order

    async def mark_paid(
        self,
        order: Order,
        *,
        provider: str,
        provider_payment_id: str,
        amount_minor: int,
        currency: str,
    ) -> Order:
        """Record a verified payment and allocate its credits, once.

        The caller must already have verified the payment with the provider.
        This method does not decide whether money arrived; it records that a
        verified payment did, and grants exactly what the order promised.
        """
        if order.credits_allocated_at is not None:
            log.info("order.already_allocated", reference=order.reference)
            return order

        # The provider must have charged what we asked for. A mismatch means
        # either a tampered checkout or a bug, and neither should grant credits.
        if amount_minor != order.total_minor:
            order.status = OrderStatus.FAILED
            order.failure_reason = (
                f"Amount mismatch: expected {order.total_minor}, provider reported {amount_minor}"
            )
            await self.db.commit()
            raise AppError("The payment amount did not match the order", code="amount_mismatch")
        if currency.upper() != order.currency.upper():
            order.status = OrderStatus.FAILED
            order.failure_reason = f"Currency mismatch: {currency} for a {order.currency} order"
            await self.db.commit()
            raise AppError("The payment currency did not match", code="currency_mismatch")

        order.status = OrderStatus.PAID
        order.provider = provider
        order.provider_payment_id = provider_payment_id
        order.paid_at = datetime.now(UTC)

        entry = await BillingService(self.db).grant(
            order.organization_id,
            order.total_credits,
            kind=CreditEntryKind.PURCHASE,
            actor_user_id=order.created_by_user_id,
            note=(
                f"{order.package_name} · {order.reference} · "
                f"{order.base_credits} + {order.bonus_credits} bonus"
            ),
        )
        entry.order_id = order.id
        order.credits_allocated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(order)

        log.info(
            "order.paid",
            reference=order.reference,
            credits=order.total_credits,
            balance_after=entry.balance_after,
        )
        return order

    async def mark_failed(self, order: Order, reason: str) -> Order:
        """A failed payment grants nothing and keeps the order for investigation."""
        if order.credits_allocated_at is not None:
            # Already paid and allocated; a later failure event is not ours.
            return order
        order.status = OrderStatus.FAILED
        order.failure_reason = reason[:300]
        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def unallocated_paid_orders(self) -> list[Order]:
        """Paid orders whose credits never landed.

        This is the "I paid but got nothing" report, and it should always be
        empty. Anything here is a real incident.
        """
        rows = await self.db.execute(
            select(Order).where(
                Order.status == OrderStatus.PAID, Order.credits_allocated_at.is_(None)
            )
        )
        return list(rows.scalars())
