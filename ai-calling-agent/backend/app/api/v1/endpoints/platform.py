"""Platform administration: every customer, their credits, and their usage.

Separate from the tenant API on purpose. Everything here crosses the
organization boundary, so it is guarded by a flag that no customer-facing path
can set, and every action that touches someone else's account is written to an
audit trail before it is applied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, PlatformAdmin
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.agent import Agent
from app.models.billing import CreditEntry, CreditEntryKind, PlatformEvent
from app.models.call import Call, CallStatus
from app.models.organization import Organization
from app.models.package import CreditPackage, Order, OrderStatus
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.platform import (
    AdminOrderRead,
    CreditDeductRequest,
    CreditEntryRead,
    CreditGrantRequest,
    OrganizationSummary,
    OrganizationUpdate,
    PackageAdminRead,
    PackageWrite,
    PlatformEventRead,
    PlatformOverview,
    PlatformUserRead,
    ProviderConnectionRead,
    ProviderHealth,
    ProviderWrite,
    SuspendRequest,
    UserProfile,
)
from app.services.billing_service import BillingService, spend_total
from app.services.order_service import OrderService
from app.services.provider_service import PROVIDER_SPECS, ProviderService

router = APIRouter(prefix="/platform", tags=["platform"])

WINDOW_DAYS = 30


def _since() -> datetime:
    return datetime.now(UTC) - timedelta(days=WINDOW_DAYS)


async def _record(
    db: DbSession,
    admin: User,
    action: str,
    *,
    organization_id: uuid.UUID | None = None,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    """Write the audit row. Called before the change, so an action that fails
    half-way still leaves evidence that it was attempted."""
    db.add(
        PlatformEvent(
            actor_user_id=admin.id,
            actor_email=admin.email,
            action=action,
            organization_id=organization_id,
            target=target,
            detail=detail,
            occurred_at=datetime.now(UTC),
        )
    )
    await db.commit()


@router.get("/overview", response_model=PlatformOverview, summary="How the business is doing")
async def overview(db: DbSession, admin: PlatformAdmin) -> PlatformOverview:
    since = _since()

    organizations = int(await db.scalar(select(func.count()).select_from(Organization)) or 0)
    suspended = int(
        await db.scalar(
            select(func.count())
            .select_from(Organization)
            .where(Organization.suspended_at.is_not(None))
        )
        or 0
    )
    users = int(await db.scalar(select(func.count()).select_from(User)) or 0)

    calls = int(
        await db.scalar(select(func.count()).select_from(Call).where(Call.created_at >= since)) or 0
    )
    seconds = float(
        await db.scalar(
            select(func.coalesce(func.sum(Call.duration_seconds), 0)).where(
                Call.created_at >= since
            )
        )
        or 0
    )
    provider_cost = float(
        await db.scalar(
            select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(Call.created_at >= since)
        )
        or 0.0
    )
    outstanding = float(
        await db.scalar(select(func.coalesce(func.sum(Organization.credit_balance), 0.0))) or 0.0
    )
    consumed = float(
        await db.scalar(
            select(func.coalesce(func.sum(-CreditEntry.amount), 0.0)).where(
                CreditEntry.kind == CreditEntryKind.USAGE, CreditEntry.created_at >= since
            )
        )
        or 0.0
    )

    return PlatformOverview(
        organizations=organizations,
        active_organizations=organizations - suspended,
        suspended=suspended,
        users=users,
        calls_30d=calls,
        minutes_30d=round(seconds / 60.0, 1),
        credits_outstanding=round(outstanding, 2),
        credits_consumed_30d=round(consumed, 2),
        provider_cost_30d_usd=round(provider_cost, 4),
        # Credits are cents of list price; margin is what we sold minus what we paid.
        gross_margin_30d_usd=round(consumed / 100.0 - provider_cost, 4),
    )


async def _summary(db, organization: Organization, since: datetime) -> OrganizationSummary:
    """One customer's headline numbers. Shared by the list and the 360 profile.

    Both views have to agree. When they were written twice they disagreed, and
    an admin comparing the list against a profile has no way to tell which one
    is lying.
    """
    user_count = int(
        await db.scalar(
            select(func.count()).select_from(User).where(User.organization_id == organization.id)
        )
        or 0
    )
    total_calls = int(
        await db.scalar(
            select(func.count()).select_from(Call).where(Call.organization_id == organization.id)
        )
        or 0
    )
    recent = await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Call.duration_seconds), 0),
            func.coalesce(func.sum(Call.cost_usd), 0.0),
            func.max(Call.created_at),
        ).where(Call.organization_id == organization.id, Call.created_at >= since)
    )
    calls_30d, seconds_30d, cost_30d, last_at = recent.one()
    used = float(
        await db.scalar(
            select(func.coalesce(func.sum(-CreditEntry.amount), 0.0)).where(
                CreditEntry.organization_id == organization.id,
                CreditEntry.kind == CreditEntryKind.USAGE,
            )
        )
        or 0.0
    )

    async def _used(start: datetime | None = None) -> float:
        clauses = [
            CreditEntry.organization_id == organization.id,
            CreditEntry.kind == CreditEntryKind.USAGE,
        ]
        if start is not None:
            clauses.append(CreditEntry.created_at >= start)
        return float(
            await db.scalar(
                select(func.coalesce(func.sum(-CreditEntry.amount), 0.0)).where(*clauses)
            )
            or 0.0
        )

    used_30d = await _used(since)
    return OrganizationSummary(
        **{
            field: getattr(organization, field)
            for field in (
                "id",
                "name",
                "slug",
                "plan",
                "is_active",
                "suspended_reason",
                "credit_balance",
                "credit_overdraft",
                "created_at",
            )
        },
        is_suspended=organization.is_suspended,
        users=user_count,
        calls=total_calls,
        calls_30d=int(calls_30d or 0),
        minutes_30d=round(float(seconds_30d or 0) / 60.0, 1),
        provider_cost_usd=round(float(cost_30d or 0.0), 4),
        credits_used=round(used, 2),
        credits_used_30d=round(used_30d, 2),
        last_call_at=last_at,
    )


@router.get("/organizations", response_model=list[OrganizationSummary], summary="Every customer")
async def organizations(db: DbSession, admin: PlatformAdmin) -> list[OrganizationSummary]:
    since = _since()
    rows = await db.execute(select(Organization).order_by(Organization.created_at.desc()))
    return [await _summary(db, organization, since) for organization in rows.scalars()]


@router.patch(
    "/organizations/{organization_id}",
    response_model=MessageResponse,
    summary="Change a customer's plan or limits",
)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    db: DbSession,
    admin: PlatformAdmin,
) -> MessageResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return MessageResponse(message="Nothing to change")

    await _record(
        db,
        admin,
        "organization.update",
        organization_id=organization_id,
        target=organization.name,
        detail=", ".join(f"{k}={v}" for k, v in changes.items()),
    )
    for field, value in changes.items():
        setattr(organization, field, value)
    await db.commit()
    return MessageResponse(message=f"Updated {organization.name}")


@router.post(
    "/organizations/{organization_id}/credits",
    response_model=MessageResponse,
    summary="Add credits to a customer",
)
async def grant_credits(
    organization_id: uuid.UUID,
    payload: CreditGrantRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> MessageResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    await _record(
        db,
        admin,
        "credits.grant",
        organization_id=organization_id,
        target=organization.name,
        detail=f"{payload.credits:.0f} credits. {payload.note}".strip(),
    )
    entry = await BillingService(db).grant(
        organization_id, payload.credits, actor_user_id=admin.id, note=payload.note or None
    )
    return MessageResponse(
        message=(
            f"Added {payload.credits:.0f} credits to {organization.name}. "
            f"New balance {entry.balance_after:.0f}."
        )
    )


@router.post(
    "/organizations/{organization_id}/credits/deduct",
    response_model=MessageResponse,
    summary="Remove credits from a customer",
)
async def deduct_credits(
    organization_id: uuid.UUID,
    payload: CreditDeductRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> MessageResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    await _record(
        db,
        admin,
        "credits.deduct",
        organization_id=organization_id,
        target=organization.name,
        detail=f"-{payload.credits:.0f} credits. {payload.note}",
    )
    entry = await BillingService(db).deduct(
        organization_id, payload.credits, actor_user_id=admin.id, note=payload.note
    )
    return MessageResponse(
        message=f"Removed {payload.credits:.0f} credits. New balance {entry.balance_after:.0f}."
    )


@router.get(
    "/organizations/{organization_id}/credits",
    response_model=list[CreditEntryRead],
    summary="A customer's credit statement",
)
async def credit_history(
    organization_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> list[CreditEntryRead]:
    rows = await db.execute(
        select(CreditEntry)
        .where(CreditEntry.organization_id == organization_id)
        .order_by(CreditEntry.created_at.desc())
        .limit(200)
    )
    return [CreditEntryRead.model_validate(entry) for entry in rows.scalars()]


@router.post(
    "/organizations/{organization_id}/suspend",
    response_model=MessageResponse,
    summary="Stop a customer placing calls",
)
async def suspend(
    organization_id: uuid.UUID, payload: SuspendRequest, db: DbSession, admin: PlatformAdmin
) -> MessageResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    await _record(
        db,
        admin,
        "organization.suspend",
        organization_id=organization_id,
        target=organization.name,
        detail=payload.reason,
    )
    await BillingService(db).suspend(organization_id, reason=payload.reason, actor_user_id=admin.id)
    return MessageResponse(message=f"{organization.name} suspended. No further calls will start.")


@router.post(
    "/organizations/{organization_id}/unsuspend",
    response_model=MessageResponse,
    summary="Let a customer place calls again",
)
async def unsuspend(
    organization_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> MessageResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    await _record(
        db,
        admin,
        "organization.unsuspend",
        organization_id=organization_id,
        target=organization.name,
    )
    await BillingService(db).unsuspend(organization_id)
    return MessageResponse(message=f"{organization.name} reinstated")


@router.get("/users", response_model=list[PlatformUserRead], summary="Every user")
async def users(
    db: DbSession, admin: PlatformAdmin, organization_id: uuid.UUID | None = None
) -> list[PlatformUserRead]:
    statement = select(User, Organization.name).join(
        Organization, Organization.id == User.organization_id
    )
    if organization_id:
        statement = statement.where(User.organization_id == organization_id)
    rows = await db.execute(statement.order_by(User.created_at.desc()))
    return [
        PlatformUserRead(
            **PlatformUserRead.model_validate(user).model_dump(exclude={"organization_name"}),
            organization_name=name,
        )
        for user, name in rows.all()
    ]


@router.post(
    "/users/{user_id}/deactivate",
    response_model=MessageResponse,
    summary="Disable a user's sign-in",
)
async def deactivate_user(
    user_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> MessageResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if user.id == admin.id:
        # Locking yourself out of the platform surface needs shell access to undo.
        raise NotFoundError("You cannot deactivate your own account")

    await _record(
        db, admin, "user.deactivate", organization_id=user.organization_id, target=user.email
    )
    user.is_active = False
    await db.commit()
    return MessageResponse(message=f"{user.email} can no longer sign in")


@router.post(
    "/users/{user_id}/activate", response_model=MessageResponse, summary="Re-enable a user"
)
async def activate_user(user_id: uuid.UUID, db: DbSession, admin: PlatformAdmin) -> MessageResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    await _record(
        db, admin, "user.activate", organization_id=user.organization_id, target=user.email
    )
    user.is_active = True
    await db.commit()
    return MessageResponse(message=f"{user.email} can sign in again")


@router.get("/events", response_model=list[PlatformEventRead], summary="Audit trail")
async def events(db: DbSession, admin: PlatformAdmin) -> list[PlatformEventRead]:
    rows = await db.execute(
        select(PlatformEvent).order_by(PlatformEvent.created_at.desc()).limit(200)
    )
    return [PlatformEventRead.model_validate(event) for event in rows.scalars()]


@router.get("/calls", response_model=list[dict], summary="Recent calls across every customer")
async def recent_calls(db: DbSession, admin: PlatformAdmin) -> list[dict]:
    rows = await db.execute(
        select(Call, Organization.name)
        .join(Organization, Organization.id == Call.organization_id)
        .order_by(Call.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": str(call.id),
            "organization": name,
            "to_number": call.to_number,
            "status": str(call.status),
            "duration_seconds": call.duration_seconds,
            "cost_usd": call.cost_usd,
            "created_at": call.created_at.isoformat(),
            "failed": call.status is CallStatus.FAILED,
        }
        for call, name in rows.all()
    ]


# --- packages ----------------------------------------------------------


def _package_admin(package: CreditPackage, *, orders_paid: int = 0, revenue: int = 0):
    return PackageAdminRead(
        **{
            field: getattr(package, field)
            for field in PackageAdminRead.model_fields
            if field
            not in {"tax_minor", "payable_minor", "total_credits", "orders_paid", "revenue_minor"}
        },
        tax_minor=package.tax_minor,
        payable_minor=package.payable_minor,
        total_credits=package.total_credits,
        orders_paid=orders_paid,
        revenue_minor=revenue,
    )


@router.get("/packages", response_model=list[PackageAdminRead], summary="All packages")
async def list_packages(db: DbSession, admin: PlatformAdmin) -> list[PackageAdminRead]:
    rows = await db.execute(
        select(CreditPackage).order_by(CreditPackage.display_order, CreditPackage.price_minor)
    )
    out: list[PackageAdminRead] = []
    for package in rows.scalars():
        sold = await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_minor), 0)).where(
                Order.package_id == package.id, Order.status == OrderStatus.PAID
            )
        )
        count, revenue = sold.one()
        out.append(_package_admin(package, orders_paid=int(count or 0), revenue=int(revenue or 0)))
    return out


@router.post(
    "/packages",
    response_model=PackageAdminRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a package",
)
async def create_package(
    payload: PackageWrite, db: DbSession, admin: PlatformAdmin
) -> PackageAdminRead:
    clash = await db.scalar(select(CreditPackage.id).where(CreditPackage.slug == payload.slug))
    if clash:
        raise ValidationFailedError("That slug is already taken", code="slug_taken")

    package = CreditPackage(**payload.model_dump())
    db.add(package)
    await db.commit()
    await db.refresh(package)
    await _record(
        db,
        admin,
        "package.create",
        target=package.name,
        detail=f"{payload.price_minor} minor, {package.total_credits} credits",
    )
    return _package_admin(package)


@router.patch("/packages/{package_id}", response_model=PackageAdminRead, summary="Edit a package")
async def update_package(
    package_id: uuid.UUID, payload: PackageWrite, db: DbSession, admin: PlatformAdmin
) -> PackageAdminRead:
    """Editing changes future purchases only.

    Past orders carry their own snapshot of the terms, so nothing here can
    alter what a customer already paid or received.
    """
    package = await db.get(CreditPackage, package_id)
    if package is None:
        raise NotFoundError("Package not found")

    await _record(
        db,
        admin,
        "package.update",
        target=package.name,
        detail=f"price {package.price_minor} -> {payload.price_minor}",
    )
    for field, value in payload.model_dump().items():
        setattr(package, field, value)
    await db.commit()
    await db.refresh(package)
    return _package_admin(package)


@router.delete("/packages/{package_id}", response_model=MessageResponse, summary="Retire a package")
async def retire_package(
    package_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> MessageResponse:
    """Deactivates rather than deletes.

    A package with sales is referenced by real orders and invoices; deleting
    it would orphan financial history.
    """
    package = await db.get(CreditPackage, package_id)
    if package is None:
        raise NotFoundError("Package not found")
    await _record(db, admin, "package.retire", target=package.name)
    package.is_active = False
    await db.commit()
    return MessageResponse(
        message=f"{package.name} retired. Existing orders and invoices are untouched."
    )


# --- orders ------------------------------------------------------------


@router.get("/orders", response_model=list[AdminOrderRead], summary="All orders")
async def list_orders(
    db: DbSession,
    admin: PlatformAdmin,
    organization_id: uuid.UUID | None = None,
    order_status: str | None = Query(default=None, alias="status"),
) -> list[AdminOrderRead]:
    statement = select(Order, Organization.name).join(
        Organization, Organization.id == Order.organization_id
    )
    if organization_id:
        statement = statement.where(Order.organization_id == organization_id)
    if order_status:
        statement = statement.where(Order.status == order_status)
    rows = await db.execute(statement.order_by(Order.created_at.desc()).limit(200))
    return [
        AdminOrderRead(
            **AdminOrderRead.model_validate(order).model_dump(exclude={"organization_name"}),
            organization_name=name,
        )
        for order, name in rows.all()
    ]


@router.get(
    "/orders/unallocated",
    response_model=list[AdminOrderRead],
    summary="Paid orders whose credits never landed",
)
async def unallocated(db: DbSession, admin: PlatformAdmin) -> list[AdminOrderRead]:
    """The "I paid but got nothing" report. Should always be empty."""
    stuck = await OrderService(db).unallocated_paid_orders()
    out: list[AdminOrderRead] = []
    for order in stuck:
        organization = await db.get(Organization, order.organization_id)
        out.append(
            AdminOrderRead(
                **AdminOrderRead.model_validate(order).model_dump(exclude={"organization_name"}),
                organization_name=organization.name if organization else "",
            )
        )
    return out


@router.post(
    "/orders/{order_id}/retry-allocation",
    response_model=MessageResponse,
    summary="Re-run a stuck credit allocation",
)
async def retry_allocation(
    order_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> MessageResponse:
    """Replay the original idempotent allocation rather than granting by hand.

    A manual grant for a paid order double-counts if the real allocation then
    succeeds, and it loses the link between the payment and its credits.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.status is not OrderStatus.PAID:
        raise ValidationFailedError("Only a paid order can be allocated", code="not_paid")
    if order.credits_allocated_at is not None:
        return MessageResponse(message="Credits were already allocated for this order")

    await _record(
        db,
        admin,
        "order.retry_allocation",
        organization_id=order.organization_id,
        target=order.reference,
    )
    order.credits_allocated_at = None
    await OrderService(db).mark_paid(
        order,
        provider=order.provider or "manual",
        provider_payment_id=order.provider_payment_id or "retried",
        amount_minor=order.total_minor,
        currency=order.currency,
    )
    return MessageResponse(message=f"Allocated {order.total_credits} credits for {order.reference}")


# --- the 360 view ------------------------------------------------------


@router.get(
    "/organizations/{organization_id}/profile",
    response_model=UserProfile,
    summary="Everything about one customer, in one response",
)
async def organization_profile(
    organization_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> UserProfile:
    """Assembled server-side on purpose.

    Eight round trips would leave the admin reading numbers taken at eight
    different moments, which is how a support conversation ends up arguing
    about a balance that changed mid-investigation.
    """
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    since = _since()
    billing = BillingService(db)

    users = await db.execute(
        select(User).where(User.organization_id == organization_id).order_by(User.created_at)
    )
    user_rows = [
        PlatformUserRead(
            **PlatformUserRead.model_validate(u).model_dump(exclude={"organization_name"}),
            organization_name=organization.name,
        )
        for u in users.scalars()
    ]

    async def _credit_sum(kind: CreditEntryKind) -> float:
        return float(
            await db.scalar(
                select(func.coalesce(func.sum(CreditEntry.amount), 0.0)).where(
                    CreditEntry.organization_id == organization_id, CreditEntry.kind == kind
                )
            )
            or 0.0
        )

    paid = await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Order.total_minor), 0),
            func.coalesce(func.sum(Order.refunded_minor), 0),
        ).where(Order.organization_id == organization_id, Order.status == OrderStatus.PAID)
    )
    paid_count, paid_minor, refunded_minor = paid.one()

    calls_total = int(
        await db.scalar(
            select(func.count()).select_from(Call).where(Call.organization_id == organization_id)
        )
        or 0
    )
    recent = await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Call.duration_seconds), 0),
            func.coalesce(func.sum(Call.cost_usd), 0.0),
        ).where(Call.organization_id == organization_id, Call.created_at >= since)
    )
    calls_30d, seconds_30d, cost_30d = recent.one()
    failed_30d = int(
        await db.scalar(
            select(func.count())
            .select_from(Call)
            .where(
                Call.organization_id == organization_id,
                Call.created_at >= since,
                Call.status == CallStatus.FAILED,
            )
        )
        or 0
    )

    source_rows = await db.execute(
        select(Call.source, func.count())
        .where(Call.organization_id == organization_id)
        .group_by(Call.source)
    )
    by_source = {str(source): int(count) for source, count in source_rows.all()}

    agent_rows = await db.execute(
        select(Agent).where(Agent.organization_id == organization_id).order_by(Agent.created_at)
    )
    agents: list[dict] = []
    for agent in agent_rows.scalars():
        stats = await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Call.duration_seconds), 0),
                func.coalesce(func.sum(Call.cost_usd), 0.0),
            ).where(Call.agent_id == agent.id)
        )
        count, seconds, cost = stats.one()
        agents.append(
            {
                "id": str(agent.id),
                "name": agent.name,
                "role_title": agent.role_title,
                "is_active": agent.is_active,
                "language": str(agent.language),
                "calls": int(count or 0),
                "minutes": round(float(seconds or 0) / 60.0, 1),
                "provider_cost_usd": round(float(cost or 0.0), 4),
                "created_at": agent.created_at.isoformat(),
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            }
        )

    call_rows = await db.execute(
        select(Call)
        .where(Call.organization_id == organization_id)
        .order_by(Call.created_at.desc())
        .limit(25)
    )
    recent_calls = [
        {
            "id": str(call.id),
            "to_number": call.to_number,
            "status": str(call.status),
            "source": str(call.source),
            "source_detail": call.source_detail,
            "mode": str(call.mode),
            "initiated_by_user_id": str(call.initiated_by_user_id)
            if call.initiated_by_user_id
            else None,
            "duration_seconds": call.duration_seconds,
            "cost_usd": call.cost_usd,
            "created_at": call.created_at.isoformat(),
        }
        for call in call_rows.scalars()
    ]

    credit_rows = await db.execute(
        select(CreditEntry)
        .where(CreditEntry.organization_id == organization_id)
        .order_by(CreditEntry.created_at.desc())
        .limit(25)
    )
    order_rows = await db.execute(
        select(Order)
        .where(Order.organization_id == organization_id)
        .order_by(Order.created_at.desc())
        .limit(25)
    )

    def _order(order: Order) -> AdminOrderRead:
        return AdminOrderRead(
            **AdminOrderRead.model_validate(order).model_dump(exclude={"organization_name"}),
            organization_name=organization.name,
        )

    orders = [_order(order) for order in order_rows.scalars()]

    return UserProfile(
        organization=await _summary(db, organization, since),
        users=user_rows,
        balance=round(organization.credit_balance, 2),
        held=await billing.held_credits(organization_id),
        spendable=await billing.spendable(organization_id),
        lifetime_purchased=round(await _credit_sum(CreditEntryKind.PURCHASE), 2),
        lifetime_granted=round(await _credit_sum(CreditEntryKind.GRANT), 2),
        lifetime_consumed=spend_total(await _credit_sum(CreditEntryKind.USAGE)),
        consumed_30d=spend_total(
            float(
                await db.scalar(
                    select(func.coalesce(func.sum(CreditEntry.amount), 0.0)).where(
                        CreditEntry.organization_id == organization_id,
                        CreditEntry.kind == CreditEntryKind.USAGE,
                        CreditEntry.created_at >= since,
                    )
                )
                or 0.0
            )
        ),
        paid_orders=int(paid_count or 0),
        paid_minor=int(paid_minor or 0),
        refunded_minor=int(refunded_minor or 0),
        calls_total=calls_total,
        calls_30d=int(calls_30d or 0),
        minutes_30d=round(float(seconds_30d or 0) / 60.0, 1),
        failed_30d=failed_30d,
        by_source=by_source,
        provider_cost_30d_usd=round(float(cost_30d or 0.0), 4),
        agents=agents,
        recent_calls=recent_calls,
        recent_credits=[CreditEntryRead.model_validate(e) for e in credit_rows.scalars()],
        recent_orders=orders,
        unallocated_orders=[o for o in orders if o.status == "paid" and not o.credits_allocated_at],
    )


# --- provider connections ---------------------------------------------


def _provider_read(connection) -> ProviderConnectionRead:  # noqa: ANN001
    spec = PROVIDER_SPECS.get(connection.slug, {})
    return ProviderConnectionRead(
        **ProviderConnectionRead.model_validate(connection).model_dump(
            exclude={"required_fields", "optional_fields", "docs_url"}
        ),
        required_fields=spec.get("required", []),
        optional_fields=spec.get("optional", []),
        docs_url=spec.get("docs"),
    )


@router.get(
    "/providers",
    response_model=list[ProviderConnectionRead],
    summary="Every provider integration",
)
async def list_providers(db: DbSession, admin: PlatformAdmin) -> list[ProviderConnectionRead]:
    """Configured connections, plus the ones that could be configured.

    Showing the unconfigured ones is the point: an admin should be able to
    see that Plivo exists and is not set up, rather than discovering the
    integration only by reading the source.
    """
    service = ProviderService(db)
    existing = {c.slug: c for c in await service.list_connections()}
    out: list[ProviderConnectionRead] = []
    for slug, spec in PROVIDER_SPECS.items():
        connection = existing.get(slug)
        if connection is not None:
            out.append(_provider_read(connection))
        else:
            out.append(
                ProviderConnectionRead(
                    id=uuid.UUID(int=0),
                    slug=slug,
                    label=spec["label"],
                    kind=str(spec["kind"]),
                    environment="live",
                    is_enabled=False,
                    priority=100,
                    status="unconfigured",
                    status_detail="Not set up yet",
                    secret_hints={},
                    config={},
                    last_checked_at=None,
                    last_synced_at=None,
                    secrets_rotated_at=None,
                    created_at=datetime.now(UTC),
                    required_fields=spec["required"],
                    optional_fields=spec["optional"],
                    docs_url=spec["docs"],
                )
            )
    return out


@router.put("/providers", response_model=ProviderConnectionRead, summary="Save credentials")
async def save_provider(
    payload: ProviderWrite, db: DbSession, admin: PlatformAdmin
) -> ProviderConnectionRead:
    """Encrypt and store. The plaintext is never returned or logged."""
    connection = await ProviderService(db).upsert(
        slug=payload.slug,
        secrets=payload.secrets,
        config=payload.config,
        label=payload.label,
        is_enabled=payload.is_enabled,
        environment=payload.environment,
        actor_id=admin.id,
    )
    # Which keys changed, never the values.
    await _record(
        db,
        admin,
        "provider.credentials_saved",
        target=payload.slug,
        detail=f"updated: {', '.join(sorted(payload.secrets)) or 'settings only'}",
    )
    return _provider_read(connection)


@router.post(
    "/providers/{connection_id}/check",
    response_model=ProviderHealth,
    summary="Test the connection",
)
async def check_provider(
    connection_id: uuid.UUID, db: DbSession, admin: PlatformAdmin
) -> ProviderHealth:
    """A real authenticated read against the vendor, not a guess from the form."""
    result = await ProviderService(db).check(connection_id)
    return ProviderHealth(ok=result.ok, detail=result.detail, checked_at=result.checked_at)


@router.post(
    "/providers/{connection_id}/toggle",
    response_model=ProviderConnectionRead,
    summary="Enable or disable",
)
async def toggle_provider(
    connection_id: uuid.UUID, enabled: bool, db: DbSession, admin: PlatformAdmin
) -> ProviderConnectionRead:
    connection = await ProviderService(db).set_enabled(connection_id, enabled)
    await _record(
        db,
        admin,
        "provider.toggled",
        target=connection.slug,
        detail="enabled" if enabled else "disabled",
    )
    return _provider_read(connection)
