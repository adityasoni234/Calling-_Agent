"""Email API: validation, sending, campaigns, suppression and unsubscribe."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, requires
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Capability
from app.models.email import (
    EmailCampaign,
    EmailCampaignStatus,
    EmailMessage,
    EmailSuppression,
    EmailSuppressionReason,
)
from app.models.lead import Lead
from app.models.lead_list import LeadListMember
from app.models.user import User
from app.schemas.common import MessageResponse, Page
from app.schemas.email import (
    CampaignCreate,
    EmailCampaignRead,
    EmailMessageRead,
    EmailSend,
    SuppressionRead,
    SuppressionWrite,
    ValidateRequest,
)
from app.services.email.smtp import get_email_provider
from app.services.email_service import SLICE, EmailService
from app.services.email_validation import EmailValidator

router = APIRouter(prefix="/email", tags=["email"])
log = get_logger(__name__)

SendUser = Annotated[User, Depends(requires(Capability.SEND_MESSAGES))]


def _campaign_read(campaign: EmailCampaign) -> EmailCampaignRead:
    return EmailCampaignRead(
        **EmailCampaignRead.model_validate(campaign).model_dump(exclude={"eligible_count"}),
        eligible_count=campaign.eligible_count,
    )


async def _campaign(db: DbSession, user: User, campaign_id: uuid.UUID) -> EmailCampaign:
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise NotFoundError("Campaign not found")
    return campaign


async def _addresses(db: DbSession, user: User, lead_list_id: uuid.UUID | None) -> list[str]:
    query = select(Lead.email).where(
        Lead.organization_id == user.organization_id, Lead.email.isnot(None)
    )
    if lead_list_id is not None:
        query = query.join(LeadListMember, LeadListMember.lead_id == Lead.id).where(
            LeadListMember.lead_list_id == lead_list_id
        )
    rows = await db.execute(query)
    return [address for address in rows.scalars() if address]


# --- readiness and validation -----------------------------------------


@router.get("/readiness", summary="Can this account send email?")
async def readiness(db: DbSession, user: CurrentUser) -> dict:
    """What is stopping email from working, in words someone can act on."""
    provider = await get_email_provider()
    blockers: list[str] = []
    if not provider.configured:
        blockers.append(
            "No email provider is configured. Add SMTP credentials or a "
            "Postmark token in provider settings."
        )

    from decimal import Decimal

    from app.models.price_book import Billable
    from app.services.pricing_engine import PricingEngine

    quote = await PricingEngine(db).quote(
        billable=Billable.EMAIL_OUTBOUND,
        organization_id=user.organization_id,
        units=Decimal(1),
    )
    unpriced = quote.source == "unpriced"
    if unpriced:
        blockers.append("Email has no published price, so messages would send but bill nothing.")

    suppressed = await db.execute(
        select(EmailSuppression).where(EmailSuppression.organization_id == user.organization_id)
    )
    return {
        "ready": not blockers,
        "blockers": blockers,
        "provider": provider.name,
        "unpriced": unpriced,
        "suppressed_total": len(list(suppressed.scalars())),
    }


@router.post("/validate", summary="Check a list before importing or sending")
async def validate(payload: ValidateRequest, db: DbSession, user: CurrentUser) -> dict:
    """Classify every address and say which method decided it.

    Available to any signed-in user: seeing whether a list is any good
    should not require permission to spend money on it.
    """
    validator = EmailValidator(db)
    batch = await validator.validate_batch(
        user.organization_id, payload.addresses, check_dns=payload.check_dns
    )
    await validator.persist(user.organization_id, batch.results)
    return {
        **batch.summary,
        "results": [r.as_dict() for r in batch.results[:500]],
        "truncated": len(batch.results) > 500,
    }


# --- sending ----------------------------------------------------------


@router.post(
    "/messages",
    response_model=EmailMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send one email",
)
async def send_email(payload: EmailSend, db: DbSession, user: SendUser) -> EmailMessageRead:
    """201 even when blocked: the request succeeded and produced a record."""
    service = EmailService(db)
    message = await service.prepare(
        organization_id=user.organization_id,
        to_address=payload.to_address,
        subject=payload.subject,
        text_body=payload.text_body,
        html_body=payload.html_body,
        from_address=payload.from_address or "",
        from_name=payload.from_name or "",
        reply_to=payload.reply_to,
        lead_id=payload.lead_id,
        user_id=user.id,
        idempotency_key=payload.idempotency_key,
        allow_risky=payload.allow_risky,
    )
    if message.status.value == "queued":
        campaign = EmailCampaign(
            organization_id=user.organization_id,
            name="one-off",
            subject=payload.subject,
            text_body=payload.text_body,
            html_body=payload.html_body,
            from_address=payload.from_address or "",
            from_name=payload.from_name or "",
            reply_to=payload.reply_to,
        )
        await service.dispatch(message, campaign=campaign)
    return EmailMessageRead.model_validate(message)


@router.get("/messages", response_model=Page[EmailMessageRead], summary="Email history")
async def list_messages(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    email_status: Annotated[str | None, Query(alias="status")] = None,
    campaign_id: uuid.UUID | None = None,
) -> Page[EmailMessageRead]:
    query = select(EmailMessage).where(EmailMessage.organization_id == user.organization_id)
    if email_status:
        query = query.where(EmailMessage.status == email_status)
    if campaign_id:
        query = query.where(EmailMessage.campaign_id == campaign_id)
    return await paginate(
        db,
        query.order_by(EmailMessage.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=EmailMessageRead,
    )


# --- campaigns --------------------------------------------------------


@router.get("/campaigns", response_model=list[EmailCampaignRead], summary="Campaigns")
async def list_campaigns(db: DbSession, user: CurrentUser) -> list[EmailCampaignRead]:
    rows = await db.execute(
        select(EmailCampaign)
        .where(EmailCampaign.organization_id == user.organization_id)
        .order_by(EmailCampaign.created_at.desc())
    )
    service = EmailService(db)
    return [_campaign_read(await service.refresh_campaign(c)) for c in rows.scalars()]


@router.post(
    "/campaigns",
    response_model=EmailCampaignRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
)
async def create_campaign(
    payload: CampaignCreate, db: DbSession, user: SendUser
) -> EmailCampaignRead:
    campaign = EmailCampaign(
        organization_id=user.organization_id,
        created_by_user_id=user.id,
        **payload.model_dump(),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return _campaign_read(campaign)


@router.post(
    "/campaigns/{campaign_id}/validate",
    summary="Validate the recipient list and quote the send",
)
async def validate_campaign(
    campaign_id: uuid.UUID, db: DbSession, user: SendUser, check_dns: bool = True
) -> dict:
    """Must run before a campaign can be approved.

    The counts a sender approves are the counts that get used, so they are
    frozen onto the campaign here rather than recomputed at send time.
    """
    campaign = await _campaign(db, user, campaign_id)
    addresses = await _addresses(db, user, campaign.lead_list_id)
    if not addresses:
        raise AppError("That list has no email addresses", code="no_recipients")
    plan = await EmailService(db).plan(campaign, addresses, check_dns=check_dns)
    return plan.as_dict()


@router.post(
    "/campaigns/{campaign_id}/{action}",
    response_model=EmailCampaignRead,
    summary="Approve, launch, pause, resume, cancel or send a batch",
)
async def control_campaign(
    campaign_id: uuid.UUID, action: str, db: DbSession, user: SendUser
) -> EmailCampaignRead:
    campaign = await _campaign(db, user, campaign_id)
    service = EmailService(db)

    if action == "approve":
        # Someone has to put their name to having consent for this list.
        if campaign.validated_at is None:
            raise AppError("Validate the list before approving it", code="not_validated")
        campaign.consent_confirmed_by_id = user.id
        campaign.consent_confirmed_at = datetime.now(UTC)
        await db.commit()
    elif action == "launch":
        if campaign.consent_confirmed_at is None:
            raise AppError(
                "Confirm you have consent to mail this list before sending",
                code="consent_required",
            )
        campaign.status = EmailCampaignStatus.RUNNING
        campaign.started_at = campaign.started_at or datetime.now(UTC)
        await db.commit()
    elif action == "pause":
        campaign.status = EmailCampaignStatus.PAUSED
        await db.commit()
    elif action == "cancel":
        campaign.status = EmailCampaignStatus.CANCELLED
        campaign.finished_at = datetime.now(UTC)
        await db.commit()
    elif action == "send-batch":
        await _send_batch(db, user, campaign, service)
    else:
        raise NotFoundError(f"Unknown action {action!r}")

    return _campaign_read(await service.refresh_campaign(campaign))


async def _send_batch(
    db: DbSession, user: User, campaign: EmailCampaign, service: EmailService
) -> None:
    """Dispatch one slice. Idempotent per recipient on campaign id + address."""
    if campaign.status is not EmailCampaignStatus.RUNNING:
        return
    addresses = await _addresses(db, user, campaign.lead_list_id)
    already = {
        row
        for row in (
            await db.execute(
                select(EmailMessage.to_address).where(EmailMessage.campaign_id == campaign.id)
            )
        ).scalars()
    }

    sent = 0
    for address in addresses:
        if sent >= SLICE:
            break
        if address.strip().lower() in already:
            continue
        sent += 1
        message = await service.prepare(
            organization_id=campaign.organization_id,
            to_address=address,
            subject=campaign.subject,
            text_body=campaign.text_body,
            html_body=campaign.html_body,
            from_address=campaign.from_address,
            from_name=campaign.from_name,
            reply_to=campaign.reply_to,
            campaign_id=campaign.id,
            allow_risky=campaign.include_risky,
            idempotency_key=f"ecamp:{campaign.id}:{address.strip().lower()}",
        )
        await service.dispatch(message, campaign=campaign)

    remaining = len(addresses) - len(already) - sent
    if remaining <= 0:
        campaign.status = EmailCampaignStatus.COMPLETED
        campaign.finished_at = datetime.now(UTC)
        await db.commit()


# --- suppression ------------------------------------------------------


@router.get("/suppressions", response_model=Page[SuppressionRead], summary="Blocked addresses")
async def list_suppressions(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
) -> Page[SuppressionRead]:
    return await paginate(
        db,
        select(EmailSuppression)
        .where(EmailSuppression.organization_id == user.organization_id)
        .order_by(EmailSuppression.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=SuppressionRead,
    )


@router.post(
    "/suppressions",
    response_model=SuppressionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Block an address",
)
async def add_suppression(
    payload: SuppressionWrite, db: DbSession, user: SendUser
) -> SuppressionRead:
    try:
        reason = EmailSuppressionReason(payload.reason)
    except ValueError:
        reason = EmailSuppressionReason.MANUAL
    suppression = await EmailService(db).suppress(
        user.organization_id, payload.address, reason=reason, detail=payload.detail
    )
    return SuppressionRead.model_validate(suppression)


@router.delete("/suppressions/{suppression_id}", summary="Unblock an address")
async def remove_suppression(
    suppression_id: uuid.UUID, db: DbSession, user: SendUser
) -> MessageResponse:
    """Hard bounces and complaints cannot be removed.

    Un-suppressing an address that bounced is how a sending domain gets
    blocked, and the person doing it rarely knows that at the time.
    """
    suppression = await db.get(EmailSuppression, suppression_id)
    if suppression is None or suppression.organization_id != user.organization_id:
        raise NotFoundError("Suppression not found")
    if suppression.reason in (
        EmailSuppressionReason.HARD_BOUNCE,
        EmailSuppressionReason.COMPLAINT,
    ):
        raise AppError(
            "A hard bounce or spam complaint cannot be removed. Mailing that "
            "address again risks your sending domain.",
            code="suppression_permanent",
        )
    await db.delete(suppression)
    await db.commit()
    return MessageResponse(message="Address unblocked")


# --- unsubscribe and webhooks -----------------------------------------


@router.get("/unsubscribe/{token}", response_class=HTMLResponse, summary="Unsubscribe")
async def unsubscribe(token: str, db: DbSession) -> HTMLResponse:
    """Public, unauthenticated, and must always answer.

    An unsubscribe link that errors is worse than one that does nothing:
    the recipient marks the mail as spam instead, which costs the sender far
    more than the unsubscribe would have.
    """
    message = await EmailService(db).unsubscribe_by_token(token)
    body = (
        "You will not receive further emails from this sender."
        if message
        else "This link has already been used, or is no longer valid."
    )
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Unsubscribed</title></head>
        <body style="font-family:system-ui,sans-serif;max-width:32rem;
        margin:4rem auto;padding:0 1.5rem;color:#2a2724;line-height:1.6">
        <h1 style="font-size:1.25rem">Unsubscribed</h1>
        <p>{body}</p></body></html>"""
    )


@router.post("/webhooks/events", summary="Provider delivery events")
async def email_events(request: Request, db: DbSession) -> dict:
    """Apply a provider event. Always 200 — retries fix nothing here."""
    payload = await request.json()
    provider = await get_email_provider()
    event = provider.parse_webhook(payload)
    if event is None:
        log.info("email.webhook_unparsed", keys=sorted(payload)[:8])
        return {"ok": True}

    await EmailService(db).apply_event(
        provider_message_id=event.provider_message_id,
        status=event.status,
        detail=event.detail,
        permanent=event.permanent,
    )
    return {"ok": True}
