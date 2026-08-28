from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import AppError, NotFoundError
from app.models.call import Call, CallStatus, CallTurn, CallUsage
from app.schemas.call import CallCreate, CallDetail, CallRead, CallTurnRead, CallUsageRead
from app.schemas.common import MessageResponse, Page
from app.services.call_service import CallService
from app.services.postcall_service import PostCallService

router = APIRouter(prefix="/calls", tags=["calls"])


async def _get(db: DbSession, user: CurrentUser, call_id: uuid.UUID) -> Call:
    call = await db.get(Call, call_id)
    if call is None or call.organization_id != user.organization_id:
        raise NotFoundError("Call not found")
    return call


@router.get("", response_model=Page[CallRead], summary="List calls")
async def list_calls(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 25,
    call_status: CallStatus | None = Query(default=None, alias="status"),
    campaign_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
) -> Page[CallRead]:
    statement = select(Call).where(Call.organization_id == user.organization_id)
    if call_status:
        statement = statement.where(Call.status == call_status)
    if campaign_id:
        statement = statement.where(Call.campaign_id == campaign_id)
    if lead_id:
        statement = statement.where(Call.lead_id == lead_id)
    return await paginate(
        db,
        statement.order_by(Call.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=CallRead,
    )


@router.post(
    "", response_model=CallRead, status_code=status.HTTP_201_CREATED, summary="Place a call"
)
async def create_call(payload: CallCreate, db: DbSession, user: CurrentUser) -> CallRead:
    call = await CallService(db).create_and_originate(
        organization_id=user.organization_id,
        agent_id=payload.agent_id,
        lead_id=payload.lead_id,
        to_number=payload.to_number,
        from_number=payload.from_number,
    )
    return CallRead.model_validate(call)


@router.get("/{call_id}", response_model=CallDetail, summary="Call detail with transcript and cost")
async def get_call(call_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallDetail:
    call = await _get(db, user, call_id)
    turns = await db.execute(
        select(CallTurn).where(CallTurn.call_id == call_id).order_by(CallTurn.turn_index)
    )
    usage = await db.execute(select(CallUsage).where(CallUsage.call_id == call_id))
    return CallDetail(
        **CallRead.model_validate(call).model_dump(),
        turns=[CallTurnRead.model_validate(turn) for turn in turns.scalars()],
        usage=[CallUsageRead.model_validate(line) for line in usage.scalars()],
    )


@router.post("/{call_id}/end", response_model=CallRead, summary="Hang up a live call")
async def end_call(call_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallRead:
    call = await CallService(db).end_call(await _get(db, user, call_id), reason="manual")
    return CallRead.model_validate(call)


@router.post("/{call_id}/transfer", response_model=MessageResponse, summary="Transfer to a human")
async def transfer_call(
    call_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    to: str = Query(min_length=6, max_length=32),
) -> MessageResponse:
    call = await _get(db, user, call_id)
    if call.status is not CallStatus.IN_PROGRESS:
        raise AppError("Only a live call can be transferred", code="not_in_progress")
    await CallService(db).transfer(call, to)
    return MessageResponse(message=f"Transferring to {to}")


@router.post(
    "/{call_id}/reprocess", response_model=MessageResponse, summary="Re-run post-call analysis"
)
async def reprocess(call_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    await _get(db, user, call_id)
    await PostCallService(db).process(call_id)
    return MessageResponse(message="Post-call processing complete")
