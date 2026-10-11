"""Email API: validation, sending, campaigns, suppression and unsubscribe."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, requires
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.config import settings
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
from app.models.email_account import EmailAccount
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
    provider = await get_email_provider(user.organization_id, db)
    blockers: list[str] = []
    if not provider.configured:
        blockers.append(
            "No mailbox is connected. Connect your Gmail or Outlook account "
            "to start sending — mail goes out from your own address."
            if settings.email_provider == "mailbox"
            else "No email provider is configured. Add SMTP credentials or a "
            "Postmark token in provider settings."
        )
    elif provider.name == "mock":
        # The mock reports itself configured so the whole path can run in
        # development. Saying "ready" on the strength of that would show a
        # healthy screen while nothing is actually delivered -- which is
        # exactly the failure this endpoint exists to prevent.
        blockers.append(
            "Running in test mode: messages are recorded but nothing is "
            "actually delivered. Set EMAIL_PROVIDER to smtp or postmark and "
            "add credentials to send for real."
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
        #: True when sends are recorded rather than delivered. The UI leads
        #: with this, because a "sent" badge that delivered nothing is worse
        #: than an error.
        "test_mode": provider.name == "mock",
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
    # Webhooks are provider-level, so no organization is in scope here.
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


# --- connected mailboxes ----------------------------------------------
#
# A customer connects the mailbox they already own. Nobody types a password
# and nobody pastes an API token -- consent happens in Google's or
# Microsoft's own dialog, and we keep only what they hand back.

_MAILBOX_STATES: dict[str, tuple[uuid.UUID, uuid.UUID | None, str, float]] = {}
_STATE_TTL = 600.0


def _mailbox_redirect(request: Request) -> str:
    """The callback URL, derived from the host the request arrived on.

    OAuth requires the redirect to match what was registered with the
    provider, exactly. Deriving it from PUBLIC_BASE_URL meant connecting
    from localhost generated a tunnel URL that Google rightly refused,
    while registering the tunnel is pointless because it rotates daily.

    Taking it from the request makes it self-consistent: connect from
    localhost and the callback is localhost; connect from the deployed API
    and it is that host. Both halves of the exchange use the same function,
    so they cannot disagree. A forged Host header cannot widen this --
    Google only accepts a redirect it already has on file.
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/email/mailbox/callback"


def _prune_states() -> None:
    import time

    now = time.time()
    for key, (_, _, _, issued) in list(_MAILBOX_STATES.items()):
        if now - issued > _STATE_TTL:
            _MAILBOX_STATES.pop(key, None)


def _account_read(account: EmailAccount) -> dict:
    """Never includes a token. Not even a hint of one."""
    return {
        "id": str(account.id),
        "provider": str(account.provider),
        "address": account.address,
        "display_name": account.display_name,
        "status": str(account.status),
        "status_detail": account.status_detail,
        "is_default": account.is_default,
        "is_usable": account.is_usable,
        "daily_limit": account.daily_limit,
        "sent_today": account.sent_today,
        "remaining_today": account.remaining_today,
        "last_sent_at": account.last_sent_at.isoformat() if account.last_sent_at else None,
        "created_at": account.created_at.isoformat(),
    }


@router.get("/mailboxes", summary="Connected sending mailboxes")
async def list_mailboxes(db: DbSession, user: CurrentUser) -> dict:
    from app.services.email.mailbox import google_configured, microsoft_configured

    rows = await db.execute(
        select(EmailAccount).where(EmailAccount.organization_id == user.organization_id)
    )
    accounts = [_account_read(a) for a in rows.scalars()]

    return {
        "accounts": accounts,
        "available": {
            "gmail": await google_configured(),
            "outlook": await microsoft_configured(),
        },
        #: Stated up front rather than discovered. Personal Gmail is far
        #: lower than people expect, and exceeding it suspends the mailbox
        #: for a day.
        "limits": {
            "gmail_personal": 500,
            "gmail_workspace": 2000,
            "outlook": 300,
        },
    }


@router.post("/mailboxes/connect", summary="Start connecting a mailbox")
async def connect_mailbox(provider: str, request: Request, db: DbSession, user: SendUser) -> dict:
    """Return the URL to send the customer to.

    The state is random, single-use and names the organization, so the
    callback cannot be replayed or pointed at another tenant.
    """
    import time

    from app.models.email_account import MailboxProvider
    from app.services.email.mailbox import authorize_url, new_state

    try:
        kind = MailboxProvider(provider)
    except ValueError as exc:
        raise NotFoundError(f"Unknown provider {provider!r}") from exc

    _prune_states()
    state = new_state()
    _MAILBOX_STATES[state] = (user.organization_id, user.id, provider, time.time())
    return {"authorize_url": await authorize_url(kind, state, _mailbox_redirect(request))}


@router.get("/mailbox/callback", summary="Where the provider sends them back")
async def mailbox_callback(
    request: Request,
    db: DbSession,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> Response:
    """Unauthenticated because the provider redirects the browser here.

    Safe because the state must be one we issued in the last ten minutes
    and it names the organization; it is consumed on use, so a replay does
    nothing.
    """
    _prune_states()
    if error:
        return _oauth_page("Could not connect", error)
    if not code or not state or state not in _MAILBOX_STATES:
        return _oauth_page(
            "Could not connect",
            "This link has expired or was already used. Start again from the Email page.",
        )

    organization_id, user_id, provider, _ = _MAILBOX_STATES.pop(state)

    from app.core.crypto import encrypt
    from app.models.email_account import MailboxProvider, MailboxStatus
    from app.services.email.mailbox import exchange_code

    try:
        grant = await exchange_code(MailboxProvider(provider), code, _mailbox_redirect(request))
    except AppError as exc:
        return _oauth_page("Could not connect", str(exc))

    found = await db.execute(
        select(EmailAccount).where(
            EmailAccount.organization_id == organization_id,
            EmailAccount.address == grant.address,
        )
    )
    account = found.scalars().first()
    if account is None:
        existing = await db.execute(
            select(EmailAccount).where(EmailAccount.organization_id == organization_id)
        )
        account = EmailAccount(
            organization_id=organization_id,
            address=grant.address,
            # The first mailbox connected becomes the default sender.
            is_default=not list(existing.scalars()),
        )
        db.add(account)

    account.provider = grant.provider
    account.display_name = grant.display_name
    account.connected_by_user_id = user_id
    account.access_token = encrypt(grant.access_token)
    account.refresh_token = encrypt(grant.refresh_token)
    account.token_expires_at = grant.expires_at
    account.scopes = grant.scopes
    account.daily_limit = grant.daily_limit
    account.status = MailboxStatus.CONNECTED
    account.status_detail = None
    await db.commit()

    return _oauth_page(
        "Mailbox connected",
        f"Emails will be sent from {grant.address}. Close this window and "
        "return to the Email page.",
    )


def _oauth_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{title}</title></head>
        <body style="font-family:system-ui,sans-serif;max-width:32rem;
        margin:4rem auto;padding:0 1.5rem;color:#2a2724;line-height:1.6">
        <h1 style="font-size:1.25rem">{title}</h1><p>{body}</p></body></html>"""
    )


@router.post("/mailboxes/{account_id}/default", summary="Send from this mailbox")
async def set_default_mailbox(account_id: uuid.UUID, db: DbSession, user: SendUser) -> dict:
    account = await db.get(EmailAccount, account_id)
    if account is None or account.organization_id != user.organization_id:
        raise NotFoundError("Mailbox not found")

    rows = await db.execute(
        select(EmailAccount).where(EmailAccount.organization_id == user.organization_id)
    )
    for other in rows.scalars():
        other.is_default = other.id == account.id
    await db.commit()
    await db.refresh(account)
    return _account_read(account)


@router.delete("/mailboxes/{account_id}", summary="Disconnect a mailbox")
async def disconnect_mailbox(
    account_id: uuid.UUID, db: DbSession, user: SendUser
) -> MessageResponse:
    """Delete the grant rather than deactivating it.

    A refresh token kept after someone asked to disconnect can still send
    mail as them. It is not ours to hold on to.
    """
    account = await db.get(EmailAccount, account_id)
    if account is None or account.organization_id != user.organization_id:
        raise NotFoundError("Mailbox not found")
    was_default = account.is_default
    await db.delete(account)
    await db.commit()

    if was_default:
        remaining = await db.execute(
            select(EmailAccount).where(EmailAccount.organization_id == user.organization_id)
        )
        if (next_account := remaining.scalars().first()) is not None:
            next_account.is_default = True
            await db.commit()

    return MessageResponse(message="Mailbox disconnected and the stored access deleted.")
