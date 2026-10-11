"""Sending email: the gates, the bounce handling, the unsubscribe path.

The assertions that matter are about what must never happen — mailing a
suppressed address, suppressing on a soft bounce, un-bouncing a message
with a late event.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.email import (
    EmailCampaign,
    EmailCampaignStatus,
    EmailMessage,
    EmailStatus,
    EmailSuppression,
    EmailSuppressionReason,
)
from app.models.organization import Organization
from app.models.price_book import Billable, PriceBook, PriceBookStatus, PriceRule, RateKind
from app.models.user import User
from app.services.email_service import EmailService
from tests.conftest import REGISTRATION

SUBJECT = "Your consultation"
BODY = "Hi there, confirming your slot."


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _price(db_session, rate: str = "0.0008") -> None:
    book = PriceBook(
        slug=f"e-{uuid.uuid4().hex[:8]}",
        name="Email",
        status=PriceBookStatus.PUBLISHED,
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        PriceRule(
            price_book_id=book.id,
            billable=Billable.EMAIL_OUTBOUND,
            rate_kind=RateKind.PER_UNIT,
            rate=Decimal(rate),
        )
    )
    await db_session.commit()


async def _send(service, org_id, address="someone@example.com", **kw):
    return await service.prepare(
        organization_id=org_id,
        to_address=address,
        subject=SUBJECT,
        text_body=BODY,
        from_address="hello@stockvala.com",
        check_dns=False,
        **kw,
    )


# --- the gates --------------------------------------------------------


async def test_a_suppressed_address_is_recorded_not_dropped(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)
    await service.suppress(org.id, "bounced@example.com", reason=EmailSuppressionReason.HARD_BOUNCE)

    message = await _send(service, org.id, "bounced@example.com")
    assert message.status is EmailStatus.BLOCKED
    assert message.verdict_at_send == "suppressed"
    assert message.sent_at is None


async def test_an_invalid_address_is_never_mailed(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session)
    message = await _send(EmailService(db_session), org.id, "not-an-address")
    assert message.status is EmailStatus.BLOCKED


async def test_a_risky_address_needs_an_explicit_opt_in(db_session, auth_headers) -> None:
    """Role accounts are real mailboxes, but mailing them raises complaints."""
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)

    blocked = await _send(service, org.id, "support@example.com")
    assert blocked.status is EmailStatus.BLOCKED

    allowed = await _send(
        service,
        org.id,
        "support@example.com",
        allow_risky=True,
        idempotency_key="risky-allowed",
    )
    assert allowed.status is EmailStatus.QUEUED


async def test_the_verdict_is_recorded_on_the_message(db_session, auth_headers) -> None:
    """ "Why did you mail that address" has to be answerable from the row."""
    org = await _org(db_session)
    await _price(db_session)
    message = await _send(EmailService(db_session), org.id)
    assert message.verdict_at_send is not None


# --- suppression semantics --------------------------------------------


async def test_suppressing_twice_is_not_an_error(db_session, auth_headers) -> None:
    """A bounce webhook can arrive more than once."""
    org = await _org(db_session)
    service = EmailService(db_session)
    first = await service.suppress(
        org.id, "x@example.com", reason=EmailSuppressionReason.HARD_BOUNCE
    )
    second = await service.suppress(
        org.id, "x@example.com", reason=EmailSuppressionReason.HARD_BOUNCE
    )
    assert first.id == second.id


async def test_a_hard_bounce_suppresses_but_a_soft_one_does_not(db_session, auth_headers) -> None:
    """The provider retries a deferral; suppressing would discard a contact."""
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)

    soft = await _send(service, org.id, "soft@example.com", idempotency_key="soft")
    soft.provider_message_id = "msg-soft"
    soft.status = EmailStatus.SENT
    hard = await _send(service, org.id, "hard@example.com", idempotency_key="hard")
    hard.provider_message_id = "msg-hard"
    hard.status = EmailStatus.SENT
    await db_session.commit()

    await service.apply_event(provider_message_id="msg-soft", status="deferred", permanent=False)
    await service.apply_event(provider_message_id="msg-hard", status="bounced", permanent=True)

    rows = {
        r.address
        for r in (
            await db_session.execute(
                select(EmailSuppression).where(EmailSuppression.organization_id == org.id)
            )
        ).scalars()
    }
    assert "hard@example.com" in rows
    assert "soft@example.com" not in rows


async def test_a_late_event_never_un_bounces_a_message(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)
    message = await _send(service, org.id, "late@example.com")
    message.provider_message_id = "msg-late"
    message.status = EmailStatus.SENT
    await db_session.commit()

    await service.apply_event(provider_message_id="msg-late", status="bounced", permanent=True)
    await service.apply_event(provider_message_id="msg-late", status="delivered")

    refreshed = await db_session.get(EmailMessage, message.id)
    assert refreshed.status is EmailStatus.BOUNCED


async def test_an_event_for_an_unknown_message_is_ignored(db_session, auth_headers) -> None:
    result = await EmailService(db_session).apply_event(
        provider_message_id="never-sent", status="delivered"
    )
    assert result is None


# --- unsubscribe ------------------------------------------------------


async def test_an_unsubscribe_token_suppresses_without_exposing_the_address(
    db_session, auth_headers
) -> None:
    """The token is in the URL so the address never has to be."""
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)
    message = await _send(service, org.id, "leaving@example.com")
    assert message.unsubscribe_token

    result = await service.unsubscribe_by_token(message.unsubscribe_token)
    assert result is not None
    assert "leaving@example.com" not in (message.unsubscribe_token or "")

    blocked = await _send(service, org.id, "leaving@example.com", idempotency_key="after-unsub")
    assert blocked.status is EmailStatus.BLOCKED


async def test_an_unknown_unsubscribe_token_is_harmless(db_session, auth_headers) -> None:
    assert await EmailService(db_session).unsubscribe_by_token("nonsense") is None


# --- pricing and idempotency ------------------------------------------


async def test_a_message_carries_the_price_it_was_sent_under(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session, rate="0.0008")
    message = await _send(EmailService(db_session), org.id)
    assert message.customer_charge_usd == Decimal("0.000800")
    assert message.price_rule_id is not None


async def test_a_retried_send_returns_the_first_message(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)
    kw = {"idempotency_key": "campaign-1-row-1"}
    first = await _send(service, org.id, **kw)
    second = await _send(service, org.id, **kw)
    assert first.id == second.id


# --- campaign planning ------------------------------------------------


async def test_a_campaign_is_planned_before_anyone_approves_it(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session, rate="0.001")
    service = EmailService(db_session)
    await service.suppress(org.id, "gone@example.com", reason=EmailSuppressionReason.COMPLAINT)

    campaign = EmailCampaign(
        organization_id=org.id,
        name="October",
        subject=SUBJECT,
        text_body=BODY,
        from_address="hello@stockvala.com",
    )
    db_session.add(campaign)
    await db_session.commit()

    plan = await service.plan(
        campaign,
        [
            "a@example.com",
            "A@EXAMPLE.COM",  # duplicate
            "gone@example.com",  # suppressed
            "rubbish",  # invalid
            "support@example.com",  # risky
        ],
        check_dns=False,
    )
    assert plan.total == 4  # after dedupe
    assert plan.suppressed == 1
    assert plan.invalid == 1
    assert plan.risky == 1
    assert campaign.status is EmailCampaignStatus.READY
    assert campaign.validated_at is not None


async def test_risky_recipients_only_count_when_the_campaign_allows_them(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    await _price(db_session)
    service = EmailService(db_session)

    for include in (False, True):
        campaign = EmailCampaign(
            organization_id=org.id,
            name=f"c-{include}",
            subject=SUBJECT,
            text_body=BODY,
            from_address="hello@stockvala.com",
            include_risky=include,
        )
        db_session.add(campaign)
        await db_session.commit()
        plan = await service.plan(campaign, ["support@example.com"], check_dns=False)
        assert plan.eligible == (1 if include else 0)
