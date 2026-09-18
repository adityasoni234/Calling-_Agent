from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.call import Call
from app.models.lead import Lead, LeadStatus
from app.models.lead_list import LeadList, LeadListMember
from app.schemas.call import CallRead
from app.schemas.common import MessageResponse, Page
from app.schemas.lead import (
    ImportResult,
    LeadCreate,
    LeadListRead,
    LeadListUpdate,
    LeadRead,
    LeadUpdate,
)
from app.services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])


async def _get(db: DbSession, user: CurrentUser, lead_id: uuid.UUID) -> Lead:
    lead = await db.get(Lead, lead_id)
    if lead is None or lead.organization_id != user.organization_id:
        raise NotFoundError("Lead not found")
    return lead


@router.get("", response_model=Page[LeadRead], summary="List and search leads")
async def list_leads(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 25,
    search: str | None = Query(default=None, max_length=200),
    lead_status: LeadStatus | None = Query(default=None, alias="status"),
    statuses: str | None = Query(
        default=None, description="Comma-separated statuses, e.g. 'qualified,converted'"
    ),
    min_score: int | None = Query(default=None, ge=0, le=100),
    sort: str = Query(default="recent", pattern="^(recent|score|name|last_called)$"),
    list_id: uuid.UUID | None = Query(default=None, description="Only leads on this sheet"),
) -> Page[LeadRead]:
    statement = select(Lead).where(Lead.organization_id == user.organization_id)
    if search:
        statement = statement.where(LeadService(db).search_filter(search))
    if lead_status:
        statement = statement.where(Lead.status == lead_status)
    if statuses:
        wanted = [value.strip() for value in statuses.split(",") if value.strip()]
        if wanted:
            statement = statement.where(Lead.status.in_(wanted))
    if min_score is not None:
        statement = statement.where(Lead.lead_score >= min_score)
    if list_id is not None:
        statement = statement.join(LeadListMember, LeadListMember.lead_id == Lead.id).where(
            LeadListMember.lead_list_id == list_id
        )

    # A pipeline view in creation order is useless: the best lead must be first.
    order = {
        "score": (Lead.lead_score.desc(), Lead.last_called_at.desc()),
        "name": (Lead.name.asc(),),
        "last_called": (Lead.last_called_at.desc().nullslast(),),
        "recent": (Lead.created_at.desc(),),
    }[sort]
    return await paginate(
        db, statement.order_by(*order), page=page, page_size=page_size, schema=LeadRead
    )


@router.post(
    "", response_model=LeadRead, status_code=status.HTTP_201_CREATED, summary="Create a lead"
)
async def create_lead(payload: LeadCreate, db: DbSession, user: CurrentUser) -> LeadRead:
    lead = await LeadService(db).create(user.organization_id, payload.model_dump())
    return LeadRead.model_validate(lead)


@router.post("/import", response_model=ImportResult, summary="Bulk import leads from CSV")
async def import_leads(
    db: DbSession, user: CurrentUser, file: UploadFile = File(...)
) -> ImportResult:
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationFailedError("Upload a .csv file", code="invalid_file_type")

    content = await file.read()
    if len(content) > settings.max_csv_bytes:
        raise ValidationFailedError("CSV is larger than 10 MB", code="file_too_large")

    # The tab is named after the file, because that is how people refer to it.
    filename = (file.filename or "Imported list").rsplit("/", 1)[-1]
    result = await LeadService(db).import_csv(
        user.organization_id,
        content,
        list_name=filename.removesuffix(".csv").removesuffix(".CSV") or filename,
        source_filename=filename,
    )
    created = result["lead_list"]
    return ImportResult(
        imported=result["imported"],
        skipped=result["skipped"],
        errors=result["errors"],
        lead_list=(
            await _list_read(db, created, user.organization_id) if created is not None else None
        ),
    )


async def _list_read(db, lead_list, organization_id: uuid.UUID) -> LeadListRead:
    count = await db.scalar(
        select(func.count())
        .select_from(LeadListMember)
        .where(LeadListMember.lead_list_id == lead_list.id)
    )
    return LeadListRead(
        **LeadListRead.model_validate(lead_list).model_dump(exclude={"lead_count"}),
        lead_count=int(count or 0),
    )


@router.get("/lists", response_model=list[LeadListRead], summary="Every uploaded sheet")
async def list_lead_lists(db: DbSession, user: CurrentUser) -> list[LeadListRead]:
    """The tabs shown above the leads table, newest upload first."""
    members = (
        select(LeadListMember.lead_list_id, func.count().label("lead_count"))
        .group_by(LeadListMember.lead_list_id)
        .subquery()
    )
    rows = await db.execute(
        select(LeadList, func.coalesce(members.c.lead_count, 0))
        .outerjoin(members, members.c.lead_list_id == LeadList.id)
        .where(LeadList.organization_id == user.organization_id)
        .order_by(LeadList.created_at.desc())
    )
    return [
        LeadListRead(
            **LeadListRead.model_validate(lead_list).model_dump(exclude={"lead_count"}),
            lead_count=int(count or 0),
        )
        for lead_list, count in rows.all()
    ]


@router.patch("/lists/{list_id}", response_model=LeadListRead, summary="Rename a sheet")
async def rename_lead_list(
    list_id: uuid.UUID, payload: LeadListUpdate, db: DbSession, user: CurrentUser
) -> LeadListRead:
    lead_list = await _get_list(db, user, list_id)
    lead_list.name = await LeadService(db).unique_list_name(user.organization_id, payload.name)
    await db.commit()
    await db.refresh(lead_list)
    return await _list_read(db, lead_list, user.organization_id)


@router.delete("/lists/{list_id}", response_model=MessageResponse, summary="Delete a sheet")
async def delete_lead_list(list_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    """Removes the grouping only. The leads themselves are never deleted here --
    losing contacts because a tab was tidied away would be indefensible."""
    lead_list = await _get_list(db, user, list_id)
    await db.delete(lead_list)
    await db.commit()
    return MessageResponse(message="Sheet removed. The leads on it were kept.")


async def _get_list(db, user, list_id: uuid.UUID) -> LeadList:
    lead_list = await db.get(LeadList, list_id)
    if lead_list is None or lead_list.organization_id != user.organization_id:
        raise NotFoundError("Lead list not found")
    return lead_list


@router.get("/{lead_id}", response_model=LeadRead, summary="Get one lead")
async def get_lead(lead_id: uuid.UUID, db: DbSession, user: CurrentUser) -> LeadRead:
    return LeadRead.model_validate(await _get(db, user, lead_id))


@router.patch("/{lead_id}", response_model=LeadRead, summary="Update a lead")
async def update_lead(
    lead_id: uuid.UUID, payload: LeadUpdate, db: DbSession, user: CurrentUser
) -> LeadRead:
    lead = await _get(db, user, lead_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)
    return LeadRead.model_validate(lead)


@router.delete("/{lead_id}", response_model=MessageResponse, summary="Delete a lead")
async def delete_lead(lead_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    await db.delete(await _get(db, user, lead_id))
    await db.commit()
    return MessageResponse(message="Lead deleted")


@router.get("/{lead_id}/calls", response_model=list[CallRead], summary="Call history for a lead")
async def lead_calls(lead_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[CallRead]:
    await _get(db, user, lead_id)
    rows = await db.execute(
        select(Call).where(Call.lead_id == lead_id).order_by(Call.created_at.desc()).limit(100)
    )
    return [CallRead.model_validate(call) for call in rows.scalars()]
