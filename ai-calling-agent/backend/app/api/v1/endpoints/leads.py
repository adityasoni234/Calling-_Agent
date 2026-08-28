from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.call import Call
from app.models.lead import Lead, LeadStatus
from app.schemas.call import CallRead
from app.schemas.common import MessageResponse, Page
from app.schemas.lead import ImportResult, LeadCreate, LeadRead, LeadUpdate
from app.services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])
MAX_CSV_BYTES = 10 * 1024 * 1024


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
    min_score: int | None = Query(default=None, ge=0, le=100),
) -> Page[LeadRead]:
    statement = select(Lead).where(Lead.organization_id == user.organization_id)
    if search:
        statement = statement.where(LeadService(db).search_filter(search))
    if lead_status:
        statement = statement.where(Lead.status == lead_status)
    if min_score is not None:
        statement = statement.where(Lead.lead_score >= min_score)
    return await paginate(
        db,
        statement.order_by(Lead.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=LeadRead,
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
    if len(content) > MAX_CSV_BYTES:
        raise ValidationFailedError("CSV is larger than 10 MB", code="file_too_large")

    result = await LeadService(db).import_csv(user.organization_id, content)
    return ImportResult(**result)


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
