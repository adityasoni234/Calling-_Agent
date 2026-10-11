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


# --- the API ----------------------------------------------------------


async def test_the_email_api_is_closed_to_anonymous_callers(client) -> None:
    assert (
        await client.post("/email/validate", json={"addresses": ["a@b.com"]})
    ).status_code == 401
    assert (await client.get("/email/campaigns")).status_code == 401


async def test_validation_through_the_api_classifies_every_address(
    client, auth_headers, db_session
) -> None:
    response = await client.post(
        "/email/validate",
        json={
            "addresses": ["good@example.com", "rubbish", "GOOD@example.com"],
            "check_dns": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["duplicates_removed"] == 1
    assert body["invalid"] == 1
    assert len(body["results"]) == 2
    # Every verdict names the method that produced it, so a claim can be
    # held to how it was reached.
    assert all(r["method"] for r in body["results"])
    assert all(r["confidence"] < 100 for r in body["results"])


async def test_sending_through_the_api_records_the_server_decided_price(
    client, auth_headers, db_session
) -> None:
    await _price(db_session, rate="0.0008")
    response = await client.post(
        "/email/messages",
        json={
            "to_address": "someone@example.com",
            "subject": SUBJECT,
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["customer_charge_usd"] == "0.000800"
    assert isinstance(body["customer_charge_usd"], str)
    assert body["verdict_at_send"]


async def test_a_blocked_send_is_a_201_with_an_explanation(
    client, auth_headers, db_session
) -> None:
    await _price(db_session)
    await client.post(
        "/email/suppressions",
        json={"address": "blocked@example.com", "reason": "manual"},
        headers=auth_headers,
    )
    response = await client.post(
        "/email/messages",
        json={
            "to_address": "blocked@example.com",
            "subject": SUBJECT,
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "blocked"


async def test_a_hard_bounce_cannot_be_unsuppressed(client, auth_headers, db_session) -> None:
    """Mailing an address that bounced is how a sending domain gets blocked."""
    org = await _org(db_session)
    suppression = await EmailService(db_session).suppress(
        org.id, "bounced@example.com", reason=EmailSuppressionReason.HARD_BOUNCE
    )
    response = await client.delete(f"/email/suppressions/{suppression.id}", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "suppression_permanent"


async def test_a_manual_block_can_be_removed(client, auth_headers, db_session) -> None:
    created = await client.post(
        "/email/suppressions",
        json={"address": "oops@example.com", "reason": "manual"},
        headers=auth_headers,
    )
    response = await client.delete(
        f"/email/suppressions/{created.json()['id']}", headers=auth_headers
    )
    assert response.status_code == 200


async def test_a_campaign_cannot_launch_without_a_consent_confirmation(
    client, auth_headers, db_session
) -> None:
    """Someone has to put their name to having permission to mail the list."""
    await _price(db_session)
    created = await client.post(
        "/email/campaigns",
        json={
            "name": "October",
            "subject": SUBJECT,
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]
    response = await client.post(f"/email/campaigns/{campaign_id}/launch", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "consent_required"


async def test_a_campaign_cannot_be_approved_before_it_is_validated(
    client, auth_headers, db_session
) -> None:
    created = await client.post(
        "/email/campaigns",
        json={
            "name": "Unvalidated",
            "subject": SUBJECT,
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    response = await client.post(
        f"/email/campaigns/{created.json()['id']}/approve", headers=auth_headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_validated"


async def test_the_unsubscribe_page_always_answers(client, auth_headers, db_session) -> None:
    """A link that errors makes the recipient press spam instead."""
    response = await client.get("/email/unsubscribe/not-a-real-token")
    assert response.status_code == 200
    assert "no longer valid" in response.text


async def test_unsubscribing_blocks_future_sends(client, auth_headers, db_session) -> None:
    org = await _org(db_session)
    await _price(db_session)
    message = await _send(EmailService(db_session), org.id, "bye@example.com")

    page = await client.get(f"/email/unsubscribe/{message.unsubscribe_token}")
    assert page.status_code == 200
    assert "will not receive" in page.text

    again = await client.post(
        "/email/messages",
        json={
            "to_address": "bye@example.com",
            "subject": SUBJECT,
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    assert again.json()["status"] == "blocked"


async def test_readiness_reports_what_is_missing(client, auth_headers, db_session) -> None:
    response = await client.get("/email/readiness", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body and "blockers" in body
    assert body["unpriced"] is True  # no email rule seeded in this test db


async def test_one_tenant_cannot_see_anothers_email(client, auth_headers, db_session) -> None:
    await _price(db_session)
    await client.post(
        "/email/messages",
        json={
            "to_address": "private@example.com",
            "subject": "Confidential",
            "text_body": BODY,
            "from_address": "hello@stockvala.com",
        },
        headers=auth_headers,
    )
    rival = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "rival3@example.com", "organization_name": "R3"},
    )
    theirs = {"Authorization": f"Bearer {rival.json()['tokens']['access_token']}"}
    assert (await client.get("/email/messages", headers=theirs)).json()["total"] == 0


async def test_test_mode_is_never_reported_as_ready(client, auth_headers, db_session) -> None:
    """The mock reports itself configured so the path can run locally.

    Treating that as "ready to send" would show a healthy screen while
    nothing is delivered, which is the failure this endpoint exists to
    prevent.
    """
    response = await client.get("/email/readiness", headers=auth_headers)
    body = response.json()
    assert body["provider"] == "mock"
    assert body["test_mode"] is True
    assert body["ready"] is False
    assert any("nothing is actually delivered" in b for b in body["blockers"])
