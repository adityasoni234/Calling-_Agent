"""SMS and WhatsApp API.

Every write is capability-gated and tenant-scoped. Prices are quoted and
charged server-side: nothing here accepts a cost or charge from the client.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, requires
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.config import settings
from app.core.errors import AppError, NotFoundError, ValidationFailedError
from app.core.permissions import Capability
from app.models.messaging import (
    Channel,
    ConsentRecord,
    Conversation,
    Message,
    MessageCampaign,
    MessageCampaignStatus,
    MessageDirection,
    MessageStatus,
    MessageTemplate,
    Suppression,
    TemplateStatus,
)
from app.models.price_book import Billable
from app.models.user import User
from app.schemas.common import MessageResponse, Page
from app.schemas.messaging import (
    CampaignCreate,
    CampaignRead,
    ConsentRead,
    ConsentWrite,
    ConversationRead,
    EstimateRequest,
    MessageRead,
    MessageSend,
    SuppressionRead,
    SuppressionWrite,
    TemplateRead,
    TemplateWrite,
)
from app.services.message_campaign_service import MessageCampaignService
from app.services.messaging.base import MessagingNotConfigured
from app.services.messaging.twilio import get_messaging_provider_async
from app.services.messaging_service import MessagingService, normalise_number
from app.services.pricing_engine import PricingEngine

router = APIRouter(prefix="/messaging", tags=["messaging"])


def _default_sender(channel: Channel) -> str:
    """WhatsApp sends from a different number than voice calls.

    Using the voice caller id for WhatsApp is rejected by Twilio with an
    error that does not say why, so the two are kept distinct here.
    """
    if channel is Channel.WHATSAPP:
        return settings.twilio_whatsapp_number or ""
    return settings.twilio_caller_id or ""


SendUser = Annotated[User, Depends(requires(Capability.SEND_MESSAGES))]
TemplateUser = Annotated[User, Depends(requires(Capability.MANAGE_TEMPLATES))]
InboxUser = Annotated[User, Depends(requires(Capability.VIEW_CONVERSATIONS))]


def _conversation_read(conversation: Conversation) -> ConversationRead:
    return ConversationRead(
        **ConversationRead.model_validate(conversation).model_dump(exclude={"session_open"}),
        session_open=conversation.session_open,
    )


def _template_read(template: MessageTemplate) -> TemplateRead:
    return TemplateRead(
        **TemplateRead.model_validate(template).model_dump(exclude={"placeholder_count"}),
        placeholder_count=template.placeholder_count,
    )


async def _template(db: DbSession, user: User, template_id: uuid.UUID) -> MessageTemplate:
    template = await db.get(MessageTemplate, template_id)
    if template is None or template.organization_id != user.organization_id:
        raise NotFoundError("Template not found")
    return template


# --- sending ----------------------------------------------------------


@router.post("/estimate", summary="What a send will cost, before committing to it")
async def estimate(payload: EstimateRequest, db: DbSession, user: CurrentUser) -> dict:
    """Recipient count, segments, provider cost, charge and margin.

    Deliberately available to any signed-in user: seeing a price should not
    require the permission to spend money.
    """
    template = await _template(db, user, payload.template_id) if payload.template_id else None
    result = await MessagingService(db).estimate(
        organization_id=user.organization_id,
        channel=payload.channel,
        recipients=payload.recipients,
        body=payload.body,
        template=template,
    )
    return result.as_dict()


@router.post(
    "/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send one message",
)
async def send_message(payload: MessageSend, db: DbSession, user: SendUser) -> MessageRead:
    """Queue a single SMS or WhatsApp message.

    Returns 201 even when the message was suppressed: the request succeeded
    and produced a record, and the body says what happened. A 4xx would make
    an opt-out look like a client bug.
    """
    service = MessagingService(db)
    template = await _template(db, user, payload.template_id) if payload.template_id else None
    provider = await get_messaging_provider_async()
    sender = payload.from_number or _default_sender(payload.channel)

    message = await service.prepare(
        organization_id=user.organization_id,
        channel=payload.channel,
        to_number=payload.to_number,
        from_number=sender,
        body=payload.body,
        template=template,
        template_variables=payload.template_variables,
        user_id=user.id,
        lead_id=payload.lead_id,
        idempotency_key=payload.idempotency_key,
        require_consent=payload.require_consent,
    )

    # A gate already stopped it, or an idempotent replay already went out.
    if message.status is not MessageStatus.QUEUED:
        return MessageRead.model_validate(message)

    if not provider.configured:
        # Recorded as failed rather than left queued forever. A message stuck
        # in "queued" looks like a delay; this says plainly that nothing was
        # sent and why.
        await service.record_dispatch(
            message,
            provider=provider.name,
            provider_message_id=None,
            error="No messaging provider is configured.",
            error_code="provider_unconfigured",
        )
        return MessageRead.model_validate(message)

    try:
        result = await provider.send(
            to_number=message.to_number,
            from_number=message.from_number,
            body=message.body,
            channel=message.channel,
            # Without this callback the message stays "sent" forever and we
            # never learn whether it arrived or what it cost.
            status_callback=f"{settings.public_base_url}/api/v1/webhooks/messaging/status",
        )
    except MessagingNotConfigured as exc:
        await service.record_dispatch(
            message,
            provider=provider.name,
            provider_message_id=None,
            error=str(exc),
            error_code="provider_unconfigured",
        )
        return MessageRead.model_validate(message)

    await service.record_dispatch(
        message,
        provider=provider.name,
        provider_message_id=result.provider_message_id,
        error=result.error_message,
        error_code=result.error_code,
    )
    return MessageRead.model_validate(message)


@router.get("/messages", response_model=Page[MessageRead], summary="Message history")
async def list_messages(
    db: DbSession,
    user: InboxUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    channel: Channel | None = None,
    message_status: Annotated[MessageStatus | None, Query(alias="status")] = None,
    direction: MessageDirection | None = None,
    conversation_id: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=64)] = None,
) -> Page[MessageRead]:
    query = select(Message).where(Message.organization_id == user.organization_id)
    if channel:
        query = query.where(Message.channel == channel)
    if message_status:
        query = query.where(Message.status == message_status)
    if direction:
        query = query.where(Message.direction == direction)
    if conversation_id:
        query = query.where(Message.conversation_id == conversation_id)
    if search:
        query = query.where(Message.to_number.ilike(f"%{search}%"))
    return await paginate(
        db,
        query.order_by(Message.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=MessageRead,
    )


@router.get("/messages/{message_id}", response_model=MessageRead, summary="One message")
async def get_message(message_id: uuid.UUID, db: DbSession, user: InboxUser) -> MessageRead:
    message = await db.get(Message, message_id)
    if message is None or message.organization_id != user.organization_id:
        raise NotFoundError("Message not found")
    return MessageRead.model_validate(message)


# --- conversations ----------------------------------------------------


@router.get("/conversations", response_model=Page[ConversationRead], summary="The inbox")
async def list_conversations(
    db: DbSession,
    user: InboxUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    channel: Channel | None = None,
    unread_only: bool = False,
    include_archived: bool = False,
) -> Page[ConversationRead]:
    query = select(Conversation).where(Conversation.organization_id == user.organization_id)
    if channel:
        query = query.where(Conversation.channel == channel)
    if unread_only:
        query = query.where(Conversation.unread_count > 0)
    if not include_archived:
        query = query.where(Conversation.is_archived.is_(False))

    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = await db.execute(
        query.order_by(Conversation.last_message_at.desc().nullslast())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page.build(
        items=[_conversation_read(c) for c in rows.scalars()],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=ConversationRead,
    summary="Mark a thread read",
)
async def mark_read(conversation_id: uuid.UUID, db: DbSession, user: InboxUser) -> ConversationRead:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.organization_id != user.organization_id:
        raise NotFoundError("Conversation not found")
    conversation.unread_count = 0
    await db.commit()
    await db.refresh(conversation)
    return _conversation_read(conversation)


@router.get("/unread", summary="Unread count for the nav badge")
async def unread(db: DbSession, user: CurrentUser) -> dict:
    return {"unread": await MessagingService(db).unread_total(user.organization_id)}


# --- templates --------------------------------------------------------


@router.get("/templates", response_model=list[TemplateRead], summary="Templates")
async def list_templates(
    db: DbSession, user: CurrentUser, channel: Channel | None = None
) -> list[TemplateRead]:
    query = select(MessageTemplate).where(MessageTemplate.organization_id == user.organization_id)
    if channel:
        query = query.where(MessageTemplate.channel == channel)
    rows = await db.execute(query.order_by(MessageTemplate.created_at.desc()))
    return [_template_read(t) for t in rows.scalars()]


@router.post(
    "/templates",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Draft a template",
)
async def create_template(
    payload: TemplateWrite, db: DbSession, user: TemplateUser
) -> TemplateRead:
    """Created as DRAFT.

    Only the provider can approve a template, so nothing here sets APPROVED.
    Letting the UI mark its own template approved is how a banned sender
    happens.
    """
    template = MessageTemplate(
        organization_id=user.organization_id,
        channel=payload.channel,
        name=payload.name,
        language=payload.language,
        category=payload.category,
        body=payload.body,
        variables=payload.variables,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _template_read(template)


@router.delete("/templates/{template_id}", summary="Delete a template")
async def delete_template(
    template_id: uuid.UUID, db: DbSession, user: TemplateUser
) -> MessageResponse:
    template = await _template(db, user, template_id)
    await db.delete(template)
    await db.commit()
    return MessageResponse(message="Template deleted")


# --- opt-outs and consent ---------------------------------------------


@router.get("/suppressions", response_model=Page[SuppressionRead], summary="Opt-outs and DND")
async def list_suppressions(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    search: Annotated[str | None, Query(max_length=32)] = None,
) -> Page[SuppressionRead]:
    query = select(Suppression).where(Suppression.organization_id == user.organization_id)
    if search:
        query = query.where(Suppression.contact_number.ilike(f"%{search}%"))
    return await paginate(
        db,
        query.order_by(Suppression.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=SuppressionRead,
    )


@router.post(
    "/suppressions",
    response_model=SuppressionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an opt-out",
)
async def add_suppression(
    payload: SuppressionWrite, db: DbSession, user: SendUser
) -> SuppressionRead:
    suppression = await MessagingService(db).opt_out(
        user.organization_id,
        payload.contact_number,
        reason=payload.reason,
        channel=payload.channel,
        note=payload.note,
    )
    return SuppressionRead.model_validate(suppression)


@router.delete("/suppressions/{suppression_id}", summary="Remove an opt-out")
async def remove_suppression(
    suppression_id: uuid.UUID, db: DbSession, user: SendUser
) -> MessageResponse:
    """Removing a suppression does not restore consent.

    The consent record was revoked when they opted out and has to be given
    again, which is the point: un-suppressing must not quietly re-authorise
    contact.
    """
    suppression = await db.get(Suppression, suppression_id)
    if suppression is None or suppression.organization_id != user.organization_id:
        raise NotFoundError("Suppression not found")
    await db.delete(suppression)
    await db.commit()
    return MessageResponse(message="Opt-out removed. Consent must be recorded again.")


@router.post(
    "/consent",
    response_model=ConsentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record consent",
)
async def record_consent(payload: ConsentWrite, db: DbSession, user: SendUser) -> ConsentRead:
    from datetime import UTC, datetime

    number, _ = normalise_number(payload.contact_number)
    consent = ConsentRecord(
        organization_id=user.organization_id,
        contact_number=number,
        channel=payload.channel,
        method=payload.method,
        granted_at=datetime.now(UTC),
        evidence=payload.evidence,
    )
    db.add(consent)
    await db.commit()
    await db.refresh(consent)
    return ConsentRead.model_validate(consent)


# --- bulk campaigns ---------------------------------------------------


def _campaign_read(campaign, progress=None) -> CampaignRead:  # noqa: ANN001
    base = CampaignRead.model_validate(campaign).model_dump(
        exclude={"percent_complete", "remaining"}
    )
    return CampaignRead(
        **base,
        percent_complete=progress.percent if progress else 0,
        remaining=progress.remaining if progress else campaign.total_recipients,
    )


@router.get("/campaigns", response_model=list[CampaignRead], summary="Bulk sends")
async def list_campaigns(db: DbSession, user: InboxUser) -> list[CampaignRead]:
    rows = await db.execute(
        select(MessageCampaign)
        .where(MessageCampaign.organization_id == user.organization_id)
        .order_by(MessageCampaign.created_at.desc())
    )
    service = MessageCampaignService(db)
    out = []
    for campaign in rows.scalars():
        out.append(_campaign_read(campaign, await service.refresh_progress(campaign)))
    return out


@router.post(
    "/campaigns",
    response_model=CampaignRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bulk send",
)
async def create_campaign(payload: CampaignCreate, db: DbSession, user: SendUser) -> CampaignRead:
    """Created as a draft, already carrying its recipient count and quote.

    Nobody should discover the cost of a five-thousand-message campaign from
    their balance afterwards.
    """
    campaign = await MessageCampaignService(db).create(
        organization_id=user.organization_id,
        name=payload.name,
        channel=payload.channel,
        body=payload.body,
        template_id=payload.template_id,
        lead_list_id=payload.lead_list_id,
        from_number=payload.from_number or settings.twilio_caller_id or "",
        messages_per_minute=payload.messages_per_minute,
        scheduled_at=payload.scheduled_at,
        user_id=user.id,
    )
    return _campaign_read(campaign)


@router.post(
    "/campaigns/{campaign_id}/{action}",
    response_model=CampaignRead,
    summary="Launch, pause, resume or cancel",
)
async def control_campaign(
    campaign_id: uuid.UUID, action: str, db: DbSession, user: SendUser
) -> CampaignRead:
    """Cancelling stops future sends; it cannot recall what already went out."""
    service = MessageCampaignService(db)
    campaign = await service.get(campaign_id, user.organization_id)

    if action in ("launch", "resume"):
        campaign = await service.launch(campaign)
    elif action == "pause":
        campaign = await service.set_status(campaign, MessageCampaignStatus.PAUSED)
    elif action == "cancel":
        campaign = await service.set_status(campaign, MessageCampaignStatus.CANCELLED)
    elif action == "send-now":
        # Dispatch one slice immediately, so the UI shows movement rather
        # than waiting on the next worker tick.
        await service.dispatch_slice(campaign)
    else:
        raise NotFoundError(f"Unknown action {action!r}")

    return _campaign_read(campaign, await service.refresh_progress(campaign))


@router.get("/readiness", summary="Can this account actually send?")
async def readiness(db: DbSession, user: CurrentUser) -> dict:
    """What is stopping each channel from working, in plain words.

    Every one of these is a condition that otherwise surfaces as a failed
    send minutes later, with a provider error that does not say which of the
    four possible causes it was. Checking them up front turns "it doesn't
    work" into a list someone can act on.
    """
    provider = await get_messaging_provider_async()
    templates = await db.execute(
        select(MessageTemplate).where(MessageTemplate.organization_id == user.organization_id)
    )
    all_templates = list(templates.scalars())
    approved = [t for t in all_templates if t.status == TemplateStatus.APPROVED]

    sms_blockers: list[str] = []
    whatsapp_blockers: list[str] = []

    if not provider.configured:
        message = (
            "No messaging provider is configured. Add Twilio credentials in "
            "the admin provider settings."
        )
        sms_blockers.append(message)
        whatsapp_blockers.append(message)
    if not settings.twilio_caller_id:
        sms_blockers.append("No SMS sender number is set (TWILIO_CALLER_ID).")
    if not settings.twilio_whatsapp_number:
        whatsapp_blockers.append(
            "No WhatsApp sender is set. WhatsApp uses a different number from "
            "voice calls — use Twilio's sandbox (+14155238886) to test, or a "
            "number approved for WhatsApp Business."
        )
    if not approved:
        whatsapp_blockers.append(
            "No approved templates. WhatsApp only allows a free-form message "
            "within 24 hours of the contact writing to you; anything else "
            "needs a template approved by Meta."
            + (
                f" You have {len(all_templates)} awaiting approval."
                if all_templates
                else " Create one under Templates."
            )
        )

    # Pricing is a blocker of a different kind: the send works but is billed
    # at nothing, which is only discovered in a monthly margin report.
    engine = PricingEngine(db)
    unpriced = []
    for channel, billable in (
        ("sms", Billable.SMS_OUTBOUND),
        ("whatsapp", Billable.WHATSAPP_OUTBOUND),
    ):
        quote = await engine.quote(
            billable=billable, organization_id=user.organization_id, units=Decimal(1)
        )
        if quote.source == "unpriced":
            unpriced.append(channel)

    return {
        "sms": {"ready": not sms_blockers, "blockers": sms_blockers},
        "whatsapp": {"ready": not whatsapp_blockers, "blockers": whatsapp_blockers},
        "provider": provider.name,
        "templates": {"total": len(all_templates), "approved": len(approved)},
        "unpriced_channels": unpriced,
    }


#: Meta's own categories. Picking the wrong one is a common rejection: a
#: promotional message submitted as UTILITY is refused on sight.
TEMPLATE_CATEGORIES = ("UTILITY", "MARKETING", "AUTHENTICATION")


@router.post(
    "/templates/{template_id}/submit",
    response_model=TemplateRead,
    summary="Send a template to Meta for approval",
)
async def submit_template(
    template_id: uuid.UUID,
    db: DbSession,
    user: TemplateUser,
    category: str = "UTILITY",
) -> TemplateRead:
    """Submit a draft for WhatsApp approval.

    Approval is Meta's decision and takes hours to days, so this only moves
    the template to PENDING. `/templates/sync` pulls the answer back.
    """
    template = await _template(db, user, template_id)
    if template.status is TemplateStatus.APPROVED:
        return _template_read(template)
    if category not in TEMPLATE_CATEGORIES:
        raise ValidationFailedError(f"Category must be one of {', '.join(TEMPLATE_CATEGORIES)}")

    from app.services.credentials import resolve
    from app.services.messaging.twilio import (
        TemplateSubmissionError,
        submit_template_for_approval,
    )

    try:
        content_sid, status_text = await submit_template_for_approval(
            credentials=await resolve("twilio"),
            name=template.name,
            body=template.body,
            language=template.language,
            category=category,
        )
    except TemplateSubmissionError as exc:
        # Recorded on the template rather than only returned, so the reason
        # survives the page refresh that follows a failed submission.
        template.status = TemplateStatus.REJECTED
        template.rejection_reason = str(exc)
        await db.commit()
        await db.refresh(template)
        raise AppError(str(exc), code="template_submission_failed") from exc

    template.provider_template_id = content_sid
    template.status = (
        TemplateStatus.APPROVED if status_text == "approved" else TemplateStatus.PENDING
    )
    template.rejection_reason = None
    template.provider_synced_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(template)
    return _template_read(template)


@router.post(
    "/templates/sync",
    response_model=list[TemplateRead],
    summary="Ask the provider what Meta decided",
)
async def sync_templates(db: DbSession, user: TemplateUser) -> list[TemplateRead]:
    """Pull approval outcomes for everything awaiting a decision.

    Pull rather than push: Meta answers out of band, and a webhook for it
    would be one more thing to configure before WhatsApp works at all.
    """
    from app.services.credentials import resolve
    from app.services.messaging.twilio import fetch_template_status

    rows = await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.organization_id == user.organization_id,
            MessageTemplate.provider_template_id.isnot(None),
            MessageTemplate.status.in_([TemplateStatus.PENDING, TemplateStatus.REJECTED]),
        )
    )
    pending = list(rows.scalars())
    if not pending:
        return await list_templates(db, user)

    credentials = await resolve("twilio")
    for template in pending:
        status_text, reason = await fetch_template_status(
            credentials=credentials, content_sid=template.provider_template_id or ""
        )
        if status_text == "approved":
            template.status = TemplateStatus.APPROVED
            template.rejection_reason = None
        elif status_text == "rejected":
            template.status = TemplateStatus.REJECTED
            template.rejection_reason = reason or "Meta rejected this template"
        template.provider_synced_at = datetime.now(UTC)
    await db.commit()
    return await list_templates(db, user)
