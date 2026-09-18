from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.agent import Agent
from app.models.call import Call
from app.models.campaign import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from app.models.lead import Lead, LeadStatus
from app.schemas.campaign import (
    AddLeadsRequest,
    CampaignCreate,
    CampaignDetail,
    CampaignImportResult,
    CampaignLeadRead,
    CampaignRead,
    CampaignStats,
    CampaignUpdate,
    DispatchResult,
)
from app.schemas.common import MessageResponse, Page
from app.services.campaign_service import ACTIVE_CALL_STATUSES, CampaignService
from app.services.lead_service import LeadService
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
    "/{campaign_id}/leads/import",
    response_model=CampaignImportResult,
    summary="Upload a CSV of people to call on this campaign",
)
async def import_campaign_leads(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> CampaignImportResult:
    """Import a CSV and put everyone in it on this campaign in one step.

    Numbers already in the address book are attached rather than skipped -- a
    duplicate row still means "call this person", and making the user import
    first and then hunt for the same people in a picker is busywork.
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationFailedError("Upload a .csv file", code="invalid_file_type")

    content = await file.read()
    if len(content) > settings.max_csv_bytes:
        raise ValidationFailedError("CSV is larger than 10 MB", code="file_too_large")

    service = CampaignService(db)
    campaign = await service.get(campaign_id, user.organization_id)

    # A campaign upload is still a sheet, and should appear as its own tab
    # on the Leads page like any other.
    filename = (file.filename or "Imported list").rsplit("/", 1)[-1]
    result = await LeadService(db).import_csv(
        user.organization_id,
        content,
        list_name=filename.removesuffix(".csv").removesuffix(".CSV") or filename,
        source_filename=filename,
    )
    phones = result["phone_numbers"]

    attached = 0
    if phones:
        rows = await db.execute(
            select(Lead.id).where(
                Lead.organization_id == user.organization_id,
                Lead.phone_number.in_(phones),
                # Never dial someone who has asked not to be called, whatever
                # the spreadsheet says.
                Lead.status != LeadStatus.DO_NOT_CALL,
            )
        )
        attached = await service.add_leads(campaign, list(rows.scalars()))

    return CampaignImportResult(
        imported=result["imported"],
        skipped=result["skipped"],
        attached=attached,
        errors=result["errors"],
    )


@router.post(
    "/{campaign_id}/dispatch", response_model=DispatchResult, summary="Run one dispatch tick"
)
async def dispatch_now(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    force: bool = Query(
        default=False,
        description="Dial immediately, ignoring the calling window and retry backoff. "
        "Budget and concurrency caps still apply.",
    ),
) -> DispatchResult:
    """Manual tick. The worker does this on a schedule; this runs one now.

    A person pressing "Dial now" expects a call this second, so ``force`` lets
    the request past the calling window they configured for the cron.
    """
    service = CampaignService(db)
    await service.get(campaign_id, user.organization_id)
    result = await service.dispatch(campaign_id, force=force)
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
