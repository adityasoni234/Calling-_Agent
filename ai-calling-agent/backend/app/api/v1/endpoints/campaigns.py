from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import NotFoundError
from app.models.agent import Agent
from app.models.call import Call
from app.models.campaign import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from app.schemas.campaign import (
    AddLeadsRequest,
    CampaignCreate,
    CampaignDetail,
    CampaignLeadRead,
    CampaignRead,
    CampaignStats,
    CampaignUpdate,
    DispatchResult,
)
from app.schemas.common import MessageResponse, Page
from app.services.campaign_service import ACTIVE_CALL_STATUSES, CampaignService
from app.tasks.queue import enqueue_campaign_dispatch

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _stats(db: DbSession, campaign: Campaign) -> CampaignStats:
    counts = dict(
        (
            await db.execute(
                select(CampaignLead.status, func.count())
                .where(CampaignLead.campaign_id == campaign.id)
                .group_by(CampaignLead.status)
            )
        ).all()
    )
    calls_made = int(
        await db.scalar(
            select(func.count()).select_from(Call).where(Call.campaign_id == campaign.id)
        )
        or 0
    )
    active = int(
        await db.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.campaign_id == campaign.id, Call.status.in_(ACTIVE_CALL_STATUSES))
        )
        or 0
    )
    cost = float(
        await db.scalar(
            select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(
                Call.campaign_id == campaign.id
            )
        )
        or 0.0
    )
    return CampaignStats(
        total_leads=sum(counts.values()),
        pending=int(counts.get(CampaignLeadStatus.PENDING, 0)),
        completed=int(counts.get(CampaignLeadStatus.COMPLETED, 0)),
        failed=int(counts.get(CampaignLeadStatus.FAILED, 0))
        + int(counts.get(CampaignLeadStatus.EXHAUSTED, 0)),
        calls_made=calls_made,
        active_calls=active,
        cost_usd=round(cost, 4),
        within_calling_hours=CampaignService(db).within_calling_hours(campaign),
    )


@router.get("", response_model=Page[CampaignRead], summary="List campaigns")
async def list_campaigns(
    db: DbSession, user: CurrentUser, page: PageParam = 1, page_size: PageSizeParam = 25
) -> Page[CampaignRead]:
    statement = (
        select(Campaign)
        .where(Campaign.organization_id == user.organization_id)
        .order_by(Campaign.created_at.desc())
    )
    return await paginate(db, statement, page=page, page_size=page_size, schema=CampaignRead)


@router.post(
    "",
    response_model=CampaignDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
)
async def create_campaign(
    payload: CampaignCreate, db: DbSession, user: CurrentUser
) -> CampaignDetail:
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or agent.organization_id != user.organization_id:
        raise NotFoundError("Agent not found")

    data = payload.model_dump(exclude={"lead_ids"})
    campaign = Campaign(organization_id=user.organization_id, **data)
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    if payload.lead_ids:
        await CampaignService(db).add_leads(campaign, payload.lead_ids)

    return CampaignDetail(
        **CampaignRead.model_validate(campaign).model_dump(), stats=await _stats(db, campaign)
    )


@router.get("/{campaign_id}", response_model=CampaignDetail, summary="Get one campaign")
async def get_campaign(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CampaignDetail:
    campaign = await CampaignService(db).get(campaign_id, user.organization_id)
    return CampaignDetail(
        **CampaignRead.model_validate(campaign).model_dump(), stats=await _stats(db, campaign)
    )


@router.patch("/{campaign_id}", response_model=CampaignRead, summary="Update a campaign")
async def update_campaign(
    campaign_id: uuid.UUID, payload: CampaignUpdate, db: DbSession, user: CurrentUser
) -> CampaignRead:
    campaign = await CampaignService(db).get(campaign_id, user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return CampaignRead.model_validate(campaign)


@router.post("/{campaign_id}/leads", response_model=MessageResponse, summary="Add leads")
async def add_leads(
    campaign_id: uuid.UUID, payload: AddLeadsRequest, db: DbSession, user: CurrentUser
) -> MessageResponse:
    service = CampaignService(db)
    campaign = await service.get(campaign_id, user.organization_id)
    added = await service.add_leads(campaign, payload.lead_ids)
    return MessageResponse(message=f"Added {added} lead(s)")


@router.get("/{campaign_id}/leads", response_model=Page[CampaignLeadRead], summary="Campaign leads")
async def campaign_leads(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
) -> Page[CampaignLeadRead]:
    await CampaignService(db).get(campaign_id, user.organization_id)
    statement = (
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_id)
        .order_by(CampaignLead.created_at)
    )
    return await paginate(db, statement, page=page, page_size=page_size, schema=CampaignLeadRead)


async def _transition(
    campaign_id: uuid.UUID, db: DbSession, user: CurrentUser, target: CampaignStatus
) -> CampaignRead:
    service = CampaignService(db)
    campaign = await service.get(campaign_id, user.organization_id)
    campaign = await service.set_status(campaign, target)
    if target is CampaignStatus.RUNNING:
        await enqueue_campaign_dispatch(campaign.id)
    return CampaignRead.model_validate(campaign)


@router.post("/{campaign_id}/start", response_model=CampaignRead, summary="Start a campaign")
async def start_campaign(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CampaignRead:
    return await _transition(campaign_id, db, user, CampaignStatus.RUNNING)


@router.post("/{campaign_id}/pause", response_model=CampaignRead, summary="Pause a campaign")
async def pause_campaign(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CampaignRead:
    return await _transition(campaign_id, db, user, CampaignStatus.PAUSED)


@router.post("/{campaign_id}/stop", response_model=CampaignRead, summary="Stop a campaign")
async def stop_campaign(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CampaignRead:
    return await _transition(campaign_id, db, user, CampaignStatus.STOPPED)


@router.post(
    "/{campaign_id}/dispatch", response_model=DispatchResult, summary="Run one dispatch tick"
)
async def dispatch_now(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> DispatchResult:
    """Manual tick. The worker does this on a schedule; this is for testing
    a campaign without waiting for the cron."""
    service = CampaignService(db)
    await service.get(campaign_id, user.organization_id)
    result = await service.dispatch(campaign_id)
    return DispatchResult(
        started=int(result.get("started", 0)), reason=str(result.get("reason", ""))
    )


@router.delete("/{campaign_id}", response_model=MessageResponse, summary="Delete a campaign")
async def delete_campaign(
    campaign_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> MessageResponse:
    campaign = await CampaignService(db).get(campaign_id, user.organization_id)
    await db.delete(campaign)
    await db.commit()
    return MessageResponse(message="Campaign deleted")
