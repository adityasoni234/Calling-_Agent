from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, requires
from app.core.config import settings as app_settings
from app.core.errors import NotFoundError
from app.core.permissions import Capability
from app.models.organization import Organization
from app.models.pricing import PricingRate
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.settings_schema import (
    OrganizationUpdate,
    PricingRateCreate,
    PricingRateRead,
    ProviderStatus,
    SettingsRead,
)
from app.schemas.user import OrganizationRead
from app.services.cost_service import CostService
from app.services.registry import provider_status

router = APIRouter(prefix="/settings", tags=["settings"])

# Which providers must be real before the platform can place a real call.
LIVE_CALL_PROVIDERS = ("telephony", "stt", "llm", "tts")


@router.get("", response_model=SettingsRead, summary="Platform configuration and provider health")
async def read_settings(db: DbSession, user: CurrentUser) -> SettingsRead:
    """Reports which providers are selected and whether their credentials are
    present. Never returns a key value -- only whether one exists."""
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    providers = provider_status()
    return SettingsRead(
        organization_name=organization.name,
        organization_timezone=organization.timezone,
        daily_budget_usd=organization.daily_budget_usd,
        monthly_budget_usd=organization.monthly_budget_usd,
        max_concurrent_calls=organization.max_concurrent_calls,
        providers={kind: ProviderStatus(**value) for kind, value in providers.items()},
        llm_model=app_settings.llm_model,
        embedding_model=app_settings.embedding_model,
        public_base_url=app_settings.public_base_url,
        max_global_concurrent_calls=app_settings.max_global_concurrent_calls,
        budget=await CostService(db).budget_state(user.organization_id),
        using_mocks=any(providers[kind]["is_mock"] for kind in LIVE_CALL_PROVIDERS),
    )


@router.patch("/organization", response_model=OrganizationRead, summary="Update the organization")
async def update_organization(
    payload: OrganizationUpdate, db: DbSession, user: CurrentUser
) -> OrganizationRead:
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    # exclude_unset, not a None check: an explicit null clears an override and
    # returns the tenant to the deployment default.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, field, value)
    await db.commit()
    await db.refresh(organization)
    return OrganizationRead.model_validate(organization)


@router.get("/pricing", response_model=list[PricingRateRead], summary="Verified pricing rates")
async def list_rates(db: DbSession, user: CurrentUser) -> list[PricingRateRead]:
    rows = await db.execute(
        select(PricingRate)
        .where(
            (PricingRate.organization_id == user.organization_id)
            | (PricingRate.organization_id.is_(None))
        )
        .order_by(PricingRate.component, PricingRate.provider)
    )
    return [
        PricingRateRead(
            id=str(rate.id),
            component=rate.component,
            provider=rate.provider,
            model=rate.model,
            unit=rate.unit,
            rate=rate.rate,
            currency=rate.currency,
            region=rate.region,
            source_url=rate.source_url,
            verified_at=rate.verified_at,
            is_active=rate.is_active,
        )
        for rate in rows.scalars()
    ]


@router.post(
    "/pricing",
    response_model=PricingRateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a rate you have verified on a vendor's rate card",
)
async def create_rate(
    payload: PricingRateCreate,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_SETTINGS))],
) -> PricingRateRead:
    """`source_url` and `verified_at` are required by the schema. Until a rate
    exists for a component, calls using it are flagged `cost_incomplete` rather
    than priced with a guess."""
    rate = PricingRate(organization_id=user.organization_id, **payload.model_dump())
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return PricingRateRead(id=str(rate.id), is_active=rate.is_active, **payload.model_dump())


@router.post("/pricing/reprice", summary="Apply new rates to previously unpriced usage")
async def reprice(db: DbSession, user: CurrentUser) -> dict[str, int | float]:
    """Rates are usually entered after the first calls have run. This completes
    those calls instead of leaving them permanently flagged."""
    return await CostService(db).reprice(user.organization_id)


@router.delete("/pricing/{rate_id}", response_model=MessageResponse, summary="Deactivate a rate")
async def delete_rate(rate_id: str, db: DbSession, user: CurrentUser) -> MessageResponse:
    rate = await db.get(PricingRate, rate_id)
    if rate is None or rate.organization_id != user.organization_id:
        raise NotFoundError("Rate not found")
    rate.is_active = False
    await db.commit()
    return MessageResponse(message="Rate deactivated")
